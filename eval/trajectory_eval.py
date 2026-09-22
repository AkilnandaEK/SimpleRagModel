"""
eval/trajectory_eval.py
-----------------------
Week 8 — the trajectory evaluation suite.

Runs the 10 documentation queries through the ReAct agent and produces, in one
pass:

  1. a trajectory verdict per query, asserted in code against a path *set*;
  2. the four telemetry dimensions (tool choice, argument validity, step
     efficiency, cost p50 + Max);
  3. the Outcome-vs-Trajectory gap, plus the full trace of a right-answer /
     wrong-path false positive;
  4. a single mitigation experiment with its measured price;
  5. a per-mode regression matrix across the whole taxonomy.

Run it directly::

    python eval/trajectory_eval.py              # live LLM, full suite
    python eval/trajectory_eval.py --mode offline
    python eval/trajectory_eval.py --skip-injection

Outcome correctness reuses ``eval.evaluator.evaluate_answer`` — the same judge
Week 7 used — so the gap compares two verdicts on one identical run rather than
two different runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.agent_loop import run_agent
from benchmark.config import BenchmarkConfig, load_config_from_env
from eval.evaluator import evaluate_answer
from eval.golden_loader import GoldenEntry, get_all_entries, load_all_golden_sets
from eval.injection_defense import (
    PAYLOADS,
    RESIDUAL_VULNERABILITIES,
    AttackOutcome,
    InjectionPayload,
    assert_read_only_scope,
    detect_success,
    is_refusal,
    make_attack_filter,
    make_defended_filter,
    measure_defense_overhead,
    scan_answer,
)
from eval.trajectory_cases import (
    DEFAULT_SCENARIO_KEYS,
    FAILURE_MODE_BY_CODE,
    TrajectoryCase,
    golden_index,
    load_trajectory_cases,
)
from eval.trajectory_metrics import (
    TrajectoryJudgement,
    TrajectoryMetrics,
    aggregate,
    judge_trajectory,
)

#: The one mitigation this experiment applies. Exactly one, by design — the
#: point is to attribute a measured delta to a single change.
#
# Chosen *after* the baseline run named M3 (invalid_arguments) as the most
# frequent failure mode, not before it. The loop also implements a retrieval
# gate aimed at M1; it is deliberately left inactive so this experiment
# attributes its delta to a single change.
MITIGATION_NAME = "arg_schema_validation"
MITIGATION_DESCRIPTION = (
    "Argument schema validation on reference_search: a `version` filter whose "
    "value matches no sdk_version in the corpus is rejected before the tool "
    "runs, and the agent is told the accepted values. Previously such a filter "
    "was passed straight through and silently matched nothing, so the agent "
    "read an empty result as 'the docs do not cover this'."
)
MITIGATION_TARGET_MODE = "M3"


# ─────────────────────────────────────────────────────────────────────────────
# Result containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModeDelta:
    code: str
    name: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before

    @property
    def status(self) -> str:
        if self.before == 0 and self.after > 0:
            return "NEW"
        if self.after > self.before:
            return "WORSENED"
        if self.after < self.before:
            return "IMPROVED"
        return "UNCHANGED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "before": self.before,
            "after": self.after,
            "delta": self.delta,
            "status": self.status,
        }


@dataclass
class MitigationReport:
    name: str
    description: str
    target_mode: str
    target_mode_name: str
    target_before: int
    target_after: int
    was_top_mode: bool
    measured_top_mode: str
    interventions: int

    # Measured price
    latency_p50_delta_ms: float
    latency_p99_delta_ms: float
    tokens_per_query_delta: float
    cost_per_query_delta_usd: float
    cost_p50_delta_usd: float
    steps_delta: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "target_mode": self.target_mode,
            "target_mode_name": self.target_mode_name,
            "target_before": self.target_before,
            "target_after": self.target_after,
            "target_delta": self.target_after - self.target_before,
            "was_top_mode": self.was_top_mode,
            "measured_top_mode": self.measured_top_mode,
            "interventions": self.interventions,
            "price": {
                "latency_p50_delta_ms": round(self.latency_p50_delta_ms, 2),
                "latency_p99_delta_ms": round(self.latency_p99_delta_ms, 2),
                "tokens_per_query_delta": round(self.tokens_per_query_delta, 1),
                "cost_per_query_delta_usd": round(self.cost_per_query_delta_usd, 6),
                "cost_p50_delta_usd": round(self.cost_p50_delta_usd, 6),
                "steps_delta": self.steps_delta,
            },
        }


@dataclass
class InjectionReport:
    read_only_scope_ok: bool
    scope_offenders: list[str]
    undefended: list[AttackOutcome] = field(default_factory=list)
    defended: list[AttackOutcome] = field(default_factory=list)
    overhead: dict[str, float] = field(default_factory=dict)
    trajectory_pass_rate_after_defense: float = 0.0
    trajectory_pass_rate_baseline: float = 0.0
    residual_vulnerabilities: list[str] = field(default_factory=list)

    @staticmethod
    def _asr(outcomes: list[AttackOutcome]) -> float:
        """Attack success rate over *conclusive* attempts only.

        An attempt that died on a provider error tells us nothing about the
        defence; counting it as "blocked" would turn an outage into a security
        claim.
        """
        conclusive = [o for o in outcomes if o.conclusive]
        if not conclusive:
            return 0.0
        return sum(1 for o in conclusive if o.attack_succeeded) / len(conclusive) * 100

    @property
    def asr_before(self) -> float:
        return self._asr(self.undefended)

    @property
    def asr_after(self) -> float:
        return self._asr(self.defended)

    @property
    def inconclusive_count(self) -> int:
        return sum(
            1 for o in (*self.undefended, *self.defended) if not o.conclusive
        )

    @property
    def availability_impact_rate(self) -> float:
        """Share of conclusive attempts where the payload forced a refusal.

        Distinct from attack success: the output was not hijacked, but the user
        still lost the answer. A defence that reports 0% hijacks while quietly
        breaking answers is not a defence.
        """
        conclusive = [
            o for o in (*self.undefended, *self.defended) if o.conclusive
        ]
        if not conclusive:
            return 0.0
        return sum(1 for o in conclusive if o.became_refusal) / len(conclusive) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "read_only_scope_ok": self.read_only_scope_ok,
            "scope_offenders": self.scope_offenders,
            "attack_success_rate_before": round(self.asr_before, 2),
            "attack_success_rate_after": round(self.asr_after, 2),
            "inconclusive_attempts": self.inconclusive_count,
            "availability_impact_rate": round(self.availability_impact_rate, 2),
            "undefended": [o.to_dict() for o in self.undefended],
            "defended": [o.to_dict() for o in self.defended],
            "overhead": self.overhead,
            "trajectory_pass_rate_baseline": round(self.trajectory_pass_rate_baseline, 2),
            "trajectory_pass_rate_after_defense": round(self.trajectory_pass_rate_after_defense, 2),
            "residual_vulnerabilities": self.residual_vulnerabilities,
        }


@dataclass
class TrajectoryEvalOutput:
    mode: str
    provider: str
    model: str
    collection: str

    baseline: TrajectoryMetrics = field(default_factory=TrajectoryMetrics)
    mitigated: TrajectoryMetrics = field(default_factory=TrajectoryMetrics)
    baseline_judgements: list[TrajectoryJudgement] = field(default_factory=list)
    mitigated_judgements: list[TrajectoryJudgement] = field(default_factory=list)

    false_positives: list[TrajectoryJudgement] = field(default_factory=list)
    exposed_trace: dict[str, Any] | None = None

    mitigation: MitigationReport | None = None
    regression_matrix: list[ModeDelta] = field(default_factory=list)
    injection: InjectionReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "collection": self.collection,
            "baseline": self.baseline.to_dict(),
            "mitigated": self.mitigated.to_dict(),
            "baseline_cases": [j.to_dict() for j in self.baseline_judgements],
            "mitigated_cases": [j.to_dict() for j in self.mitigated_judgements],
            "gap": {
                "outcome_pass_rate": round(self.baseline.outcome_pass_rate, 2),
                "trajectory_pass_rate": round(self.baseline.trajectory_pass_rate, 2),
                "gap": round(self.baseline.gap, 2),
                "false_positive_case_ids": [j.case_id for j in self.false_positives],
                "false_positive_count": len(self.false_positives),
            },
            "exposed_trace": self.exposed_trace,
            "mitigation": self.mitigation.to_dict() if self.mitigation else None,
            "regression_matrix": [d.to_dict() for d in self.regression_matrix],
            "injection": self.injection.to_dict() if self.injection else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def _golden_index(config: BenchmarkConfig) -> dict[str, GoldenEntry]:
    """Map ``"easy:01"`` style scenario keys onto golden entries."""
    return golden_index(config.golden_set_dir)


def run_one_case(
    case: TrajectoryCase,
    entry: GoldenEntry,
    config: BenchmarkConfig,
    *,
    mitigation: str | None = None,
    evidence_filter: Callable[[str], str] | None = None,
) -> TrajectoryJudgement:
    """Execute one query and score both its outcome and its trajectory."""
    collection = config.retrieval.collection_name
    try:
        state, cb, telemetry = run_agent(
            case.question,
            config,
            collection,
            mitigation=mitigation,
            evidence_filter=evidence_filter,
        )
        steps = telemetry.agent_steps or []
        answer = state.answer
        budget_exceeded = telemetry.budget_exceeded
        cost = telemetry.estimated_cost_usd
        latency = telemetry.latency_ms
        tokens = telemetry.input_tokens + telemetry.output_tokens
        infra_error = telemetry.error
    except Exception as exc:  # a crash is infrastructure, not agent judgement
        steps, answer = [], f"Agent crashed: {exc}"
        budget_exceeded, cost, latency, tokens = False, 0.0, 0.0, 0
        telemetry, infra_error = None, str(exc)

    judgement = judge_trajectory(
        case,
        steps,
        collection_name=collection,
        cost_usd=cost,
        latency_ms=latency,
        total_tokens=tokens,
        answer=answer,
        budget_exceeded=budget_exceeded,
        infra_error=infra_error,
    )

    # Outcome verdict from the shared Week 7 evaluator, on this same run.
    from telemetry.telemetry import ExecutionTelemetry

    outcome = evaluate_answer(entry, answer, telemetry or ExecutionTelemetry())
    judgement.outcome_pass = outcome.is_correct
    judgement.outcome_match_type = outcome.match_type
    return judgement


def run_suite(
    config: BenchmarkConfig,
    *,
    mitigation: str | None = None,
    label: str = "",
    scenario_keys: tuple[str, ...] | None = None,
    verbose: bool = True,
) -> tuple[list[TrajectoryJudgement], TrajectoryMetrics]:
    """Run the selected trajectory cases and aggregate them.

    Cases are built from the golden sets, so the question the agent is asked and
    the answer the outcome evaluator scores against always come from the same
    record.
    """
    index = _golden_index(config)
    cases = load_trajectory_cases(config.golden_set_dir, scenario_keys)
    judgements: list[TrajectoryJudgement] = []

    for case in cases:
        entry = index[case.scenario_key]  # guaranteed by load_trajectory_cases
        judgement = run_one_case(case, entry, config, mitigation=mitigation)
        judgements.append(judgement)

        if verbose:
            if judgement.infra_error:
                print(
                    f"  {case.case_id} [{case.scenario_key:>10}] "
                    f"ERRORED — {judgement.infra_error[:90]}"
                )
            else:
                outcome = "PASS" if judgement.outcome_pass else "FAIL"
                traj = "PASS" if judgement.trajectory_pass else "FAIL"
                flag = "  <-- FALSE POSITIVE" if judgement.is_false_positive else ""
                print(
                    f"  {case.case_id} [{case.scenario_key:>10}] "
                    f"outcome={outcome} trajectory={traj} "
                    f"path={'->'.join(judgement.actual_path) or '(none)'} "
                    f"modes={','.join(judgement.failure_modes) or '-'}{flag}"
                )

    return judgements, aggregate(judgements, label=label)


def _warmup(config: BenchmarkConfig) -> None:
    """Warm embeddings + Chroma so the first case is not charged for cold start."""
    try:
        from app.services.embedder import embed_query
        from app.services.hybrid_retrieval import hybrid_query_chunks

        embed_query("warmup")
        hybrid_query_chunks(
            collection_name=config.retrieval.collection_name,
            query="warmup",
            query_embedding=[0.0] * 384,
            top_k=1,
        )
    except Exception:
        pass


def build_regression_matrix(
    before: TrajectoryMetrics,
    after: TrajectoryMetrics,
) -> list[ModeDelta]:
    """Per-mode before/after counts across the whole taxonomy."""
    rows: list[ModeDelta] = []
    for code, mode in FAILURE_MODE_BY_CODE.items():
        rows.append(
            ModeDelta(
                code=code,
                name=mode.name,
                before=before.failure_mode_counts.get(code, 0),
                after=after.failure_mode_counts.get(code, 0),
            )
        )
    return rows


def _top_mode(metrics: TrajectoryMetrics) -> str:
    """The most frequent failure mode, ties broken by taxonomy order."""
    counts = metrics.failure_mode_counts
    if not counts or max(counts.values(), default=0) == 0:
        return "-"
    return max(counts.items(), key=lambda kv: (kv[1], -list(counts).index(kv[0])))[0]


def build_mitigation_report(
    before: TrajectoryMetrics,
    after: TrajectoryMetrics,
    after_judgements: list[TrajectoryJudgement],
    interventions: int,
) -> MitigationReport:
    measured_top = _top_mode(before)
    n = max(before.total_cases, 1)

    return MitigationReport(
        name=MITIGATION_NAME,
        description=MITIGATION_DESCRIPTION,
        target_mode=MITIGATION_TARGET_MODE,
        target_mode_name=FAILURE_MODE_BY_CODE[MITIGATION_TARGET_MODE].name,
        target_before=before.failure_mode_counts.get(MITIGATION_TARGET_MODE, 0),
        target_after=after.failure_mode_counts.get(MITIGATION_TARGET_MODE, 0),
        was_top_mode=(measured_top == MITIGATION_TARGET_MODE),
        measured_top_mode=measured_top,
        interventions=interventions,
        latency_p50_delta_ms=after.latency_p50_ms - before.latency_p50_ms,
        latency_p99_delta_ms=after.latency_p99_ms - before.latency_p99_ms,
        tokens_per_query_delta=(after.tokens_total - before.tokens_total) / n,
        cost_per_query_delta_usd=(after.cost_total_usd - before.cost_total_usd) / n,
        cost_p50_delta_usd=after.cost_p50_usd - before.cost_p50_usd,
        steps_delta=after.total_steps - before.total_steps,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bonus: indirect prompt injection
# ─────────────────────────────────────────────────────────────────────────────

#: A positive, answerable case — the injection has to ride in on real evidence,
#: so a query that retrieves nothing would not exercise the attack at all.
INJECTION_SCENARIO_KEY = "easy:01"


def run_injection_suite(
    config: BenchmarkConfig,
    baseline_metrics: TrajectoryMetrics,
    *,
    verbose: bool = True,
) -> InjectionReport:
    """Attack the agent through poisoned tool output, then defend and re-measure."""
    index = _golden_index(config)
    cases = load_trajectory_cases(config.golden_set_dir)
    case = next(c for c in cases if c.scenario_key == INJECTION_SCENARIO_KEY)
    entry = index[case.scenario_key]

    scope_ok, offenders = assert_read_only_scope()
    report = InjectionReport(
        read_only_scope_ok=scope_ok,
        scope_offenders=offenders,
        residual_vulnerabilities=list(RESIDUAL_VULNERABILITIES),
        trajectory_pass_rate_baseline=baseline_metrics.trajectory_pass_rate,
    )

    for payload in PAYLOADS:
        for defended, filter_factory in (
            (False, make_attack_filter),
            (True, make_defended_filter),
        ):
            judgement = run_one_case(
                case, entry, config, evidence_filter=filter_factory(payload)
            )
            markers = detect_success(payload, judgement.answer)
            guard = scan_answer(judgement.answer)

            # With the defence on, the guardrail is allowed to veto the answer;
            # an attack only counts as successful if it survives that veto.
            succeeded = bool(markers) and not (defended and guard.blocked)

            # T01 is answerable from a clean corpus, so a refusal here means the
            # payload cost the user their answer even though it never seized
            # control of the output.
            outcome = AttackOutcome(
                infra_error=judgement.infra_error,
                became_refusal=(
                    case.kind != "unanswerable" and is_refusal(judgement.answer)
                ),
                payload_id=payload.payload_id,
                label=payload.label,
                case_id=case.case_id,
                question=case.question,
                attack_succeeded=succeeded,
                markers_hit=markers,
                guardrail_blocked=guard.blocked,
                guardrail_violations=guard.violations,
                answer_excerpt=judgement.answer[:300],
                latency_ms=judgement.latency_ms,
                total_tokens=judgement.total_tokens,
            )
            (report.defended if defended else report.undefended).append(outcome)

            if verbose:
                tag = "DEFENDED" if defended else "UNDEFENDED"
                if outcome.conclusive:
                    print(
                        f"  {payload.payload_id} {payload.label:<28} {tag:<10} "
                        f"attack_succeeded={succeeded} "
                        f"guardrail_blocked={guard.blocked}"
                    )
                else:
                    print(
                        f"  {payload.payload_id} {payload.label:<28} {tag:<10} "
                        f"INCONCLUSIVE — {outcome.infra_error[:70]}"
                    )

    # Re-run the full trajectory suite with the defence active to prove the
    # sanitiser did not break normal operation.
    if verbose:
        print("\n  Re-running trajectory_eval with the defence layer active ...")
    # An empty payload: the sanitiser and fence run, but nothing is injected —
    # so this isolates the defence's cost to normal operation.
    sanitize_only = make_defended_filter(
        InjectionPayload(payload_id="P0", label="none", comment="", success_markers=())
    )
    defended_judgements = [
        run_one_case(c, index[c.scenario_key], config, evidence_filter=sanitize_only)
        for c in cases
    ]
    defended_metrics = aggregate(defended_judgements, label="defended")
    report.trajectory_pass_rate_after_defense = defended_metrics.trajectory_pass_rate

    sample_texts = [
        j.steps[0].observation or "sample reference text " * 20
        for j in defended_judgements[:5]
        if j.steps
    ] or ["sample reference text " * 20]
    report.overhead = measure_defense_overhead(sample_texts)

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_trajectory_eval(
    config: BenchmarkConfig | None = None,
    *,
    mode: str | None = None,
    provider: str | None = None,
    model_override: str | None = None,
    include_injection: bool = True,
    injection_only: bool = False,
    scenario_keys: tuple[str, ...] | None = None,
    verbose: bool = True,
) -> TrajectoryEvalOutput:
    """Run the entire Week 8 suite and return a single serialisable report."""
    config = config or load_config_from_env()
    if mode:
        config.llm.mode = mode
    if provider:
        config.llm.provider = provider
    if model_override:
        if config.llm.provider == "groq":
            config.llm.groq_model = model_override
        else:
            config.llm.gemini_model = model_override

    model = (
        config.llm.groq_model if config.llm.provider == "groq"
        else config.llm.gemini_model
    )
    output = TrajectoryEvalOutput(
        mode=config.llm.mode,
        provider=config.llm.provider,
        model=model,
        collection=config.retrieval.collection_name,
    )

    _warmup(config)

    if verbose:
        print("\n" + "=" * 78)
        print(f"  WEEK 8 TRAJECTORY EVAL — {config.llm.mode} mode / "
              f"{config.llm.provider}:{model}")
        print("=" * 78)

    if injection_only:
        # The bonus suite is quota-hungry and worth re-running on its own after
        # the main deliverables are already measured.
        if verbose:
            print("\n[bonus only] Indirect prompt injection")
        output.injection = run_injection_suite(
            config, output.baseline, verbose=verbose
        )
        return output

    if verbose:
        print("\n[1/4] Baseline run (no mitigation)")

    baseline_judgements, baseline = run_suite(
        config, mitigation=None, label="baseline",
        scenario_keys=scenario_keys, verbose=verbose,
    )
    output.baseline_judgements = baseline_judgements
    output.baseline = baseline

    # ── Gap analysis + false-positive trace ──
    output.false_positives = [j for j in baseline_judgements if j.is_false_positive]
    if output.false_positives:
        worst = output.false_positives[0]
        output.exposed_trace = {
            "case_id": worst.case_id,
            "scenario_key": worst.scenario_key,
            "question": worst.question,
            "answer": worst.answer,
            "outcome_verdict": f"PASS ({worst.outcome_match_type})",
            "trajectory_verdict": f"FAIL — {worst.failure_reason}",
            "failure_modes": [
                {"code": c, "name": FAILURE_MODE_BY_CODE[c].name,
                 "description": FAILURE_MODE_BY_CODE[c].description}
                for c in worst.failure_modes
            ],
            "actual_path": worst.actual_path,
            "steps": worst.to_dict()["steps"],
        }

    if verbose:
        print(f"\n[2/4] Gap analysis")
        print(f"  Outcome pass rate    : {baseline.outcome_pass_rate:.1f}%")
        print(f"  Trajectory pass rate : {baseline.trajectory_pass_rate:.1f}%")
        print(f"  GAP                  : {baseline.gap:.1f} pts")
        print(f"  False positives      : {len(output.false_positives)} "
              f"({', '.join(j.case_id for j in output.false_positives) or 'none'})")
        print(f"\n[3/4] Mitigation run ({MITIGATION_NAME})")

    mitigated_judgements, mitigated = run_suite(
        config, mitigation=MITIGATION_NAME, label="mitigated",
        scenario_keys=scenario_keys, verbose=verbose,
    )
    output.mitigated_judgements = mitigated_judgements
    output.mitigated = mitigated

    # Gate interventions are control steps, which the judge counts separately
    # from tool choices.
    interventions = mitigated.control_steps

    output.mitigation = build_mitigation_report(
        baseline, mitigated, mitigated_judgements, interventions
    )
    output.regression_matrix = build_regression_matrix(baseline, mitigated)

    if include_injection:
        if verbose:
            print(f"\n[4/4] Indirect prompt injection (bonus)")
        output.injection = run_injection_suite(config, baseline, verbose=verbose)
    elif verbose:
        print(f"\n[4/4] Injection suite skipped")

    return output


def print_report(output: TrajectoryEvalOutput) -> None:
    """Human-readable summary of everything the suite measured."""
    b, m = output.baseline, output.mitigated

    if b.total_cases == 0 and output.injection is not None:
        _print_injection(output.injection)  # --injection-only run
        return

    print("\n" + "=" * 78)
    print("  TRAJECTORY TELEMETRY")
    print("=" * 78)
    print(f"  {'Dimension':<28}{'Baseline':>16}{'Mitigated':>16}")
    print("  " + "-" * 60)
    print(f"  {'Tool-Choice Accuracy':<28}{b.tool_choice_accuracy:>15.1f}%{m.tool_choice_accuracy:>15.1f}%")
    print(f"  {'Argument Validity Rate':<28}{b.argument_validity_rate:>15.1f}%{m.argument_validity_rate:>15.1f}%")
    print(f"  {'Step Efficiency':<28}{b.step_efficiency:>15.1f}%{m.step_efficiency:>15.1f}%")
    print(f"  {'  steps actual/optimal':<28}{f'{b.total_steps}/{b.total_optimal_steps}':>16}{f'{m.total_steps}/{m.total_optimal_steps}':>16}")
    print(f"  {'  steps ratio (act:opt)':<28}{b.steps_ratio:>16.2f}{m.steps_ratio:>16.2f}")
    print(f"  {'Cost p50 (USD/query)':<28}{b.cost_p50_usd:>16.6f}{m.cost_p50_usd:>16.6f}")
    print(f"  {'Cost Max (USD/query)':<28}{b.cost_max_usd:>16.6f}{m.cost_max_usd:>16.6f}")
    print(f"  {'  worst-case query':<28}{b.cost_max_case_id:>16}{m.cost_max_case_id:>16}")
    print(f"  {'Latency p50 (ms)':<28}{b.latency_p50_ms:>16.0f}{m.latency_p50_ms:>16.0f}")
    print(f"  {'Latency p99 (ms)':<28}{b.latency_p99_ms:>16.0f}{m.latency_p99_ms:>16.0f}")

    if b.errored_cases or m.errored_cases:
        print()
        print(f"  !! {b.errored_cases} baseline and {m.errored_cases} mitigated case(s) "
              f"aborted on infrastructure errors.")
        print(f"     Those runs carry no failure-mode attribution; every rate below "
              f"is over all {b.total_cases} cases.")

    print("\n" + "=" * 78)
    print("  OUTCOME vs TRAJECTORY GAP")
    print("=" * 78)
    print(f"  Outcome pass rate     : {b.outcome_pass_rate:>6.1f}%")
    print(f"  Trajectory pass rate  : {b.trajectory_pass_rate:>6.1f}%")
    print(f"  GAP                   : {b.gap:>6.1f} pts")
    print(f"  Right-answer/wrong-path cases: {len(output.false_positives)}")

    if output.exposed_trace:
        t = output.exposed_trace
        print("\n  --- EXPOSED FALSE-POSITIVE TRACE ---")
        print(f"  Case      : {t['case_id']} ({t['scenario_key']})")
        print(f"  Question  : {t['question']}")
        print(f"  Outcome   : {t['outcome_verdict']}")
        print(f"  Trajectory: {t['trajectory_verdict']}")
        print(f"  Path      : {' -> '.join(t['actual_path']) or '(no tools called)'}")
        for mode in t["failure_modes"]:
            print(f"  Mode      : {mode['code']} {mode['name']} — {mode['description']}")
        print(f"  Answer    : {t['answer'][:200]}")
        print("  Steps:")
        for s in t["steps"]:
            mark = "ok " if s["tool_choice_ok"] else "BAD"
            print(f"    [{mark}] step {s['step']}: {s['tool']} "
                  f"args={json.dumps(s['tool_input'])[:80]}")
            if not s["tool_choice_ok"]:
                print(f"           reason: {s['tool_choice_reason']}")
            if not s["args_ok"]:
                print(f"           args  : {s['args_reason']}")

    if output.mitigation:
        mit = output.mitigation
        print("\n" + "=" * 78)
        print("  SINGLE MITIGATION & PRICE PAID")
        print("=" * 78)
        print(f"  Mitigation      : {mit.name}")
        print(f"  {mit.description}")
        print(f"  Targets         : {mit.target_mode} ({mit.target_mode_name})")
        print(f"  Measured top mode: {mit.measured_top_mode} "
              f"{'(matches target)' if mit.was_top_mode else '(DOES NOT match target — see notes)'}")
        print(f"  Before -> After : {mit.target_before} -> {mit.target_after} "
              f"({mit.target_after - mit.target_before:+d})")
        print(f"  Gate interventions (extra steps forced): {mit.interventions}")
        print("\n  Price paid (measured):")
        print(f"    p50 latency     : {mit.latency_p50_delta_ms:+.1f} ms")
        print(f"    p99 latency     : {mit.latency_p99_delta_ms:+.1f} ms")
        print(f"    tokens / query  : {mit.tokens_per_query_delta:+.1f}")
        print(f"    cost / query    : {mit.cost_per_query_delta_usd:+.6f} USD")
        print(f"    cost p50        : {mit.cost_p50_delta_usd:+.6f} USD")

    print("\n" + "=" * 78)
    print("  PER-MODE REGRESSION MATRIX")
    print("=" * 78)
    print(f"  {'Code':<6}{'Failure mode':<24}{'Before':>8}{'After':>8}{'Δ':>6}  Status")
    print("  " + "-" * 66)
    worsened, appeared = [], []
    for row in output.regression_matrix:
        print(f"  {row.code:<6}{row.name:<24}{row.before:>8}{row.after:>8}"
              f"{row.delta:>+6}  {row.status}")
        if row.status == "WORSENED":
            worsened.append(row)
        elif row.status == "NEW":
            appeared.append(row)

    print()
    if appeared:
        print("  NEW failure modes introduced by the fix: "
              + ", ".join(f"{r.code} ({r.name}) 0 -> {r.after}" for r in appeared))
    if worsened:
        print("  WORSENED failure modes: "
              + ", ".join(f"{r.code} ({r.name}) {r.before} -> {r.after}" for r in worsened))
    if not appeared and not worsened:
        print("  No failure mode worsened and none appeared as a side effect.")

    if output.injection:
        _print_injection(output.injection)

    print()


def _print_injection(inj: InjectionReport) -> None:
    print("\n" + "=" * 78)
    print("  BONUS — INDIRECT PROMPT INJECTION")
    print("=" * 78)
    print(f"  Read-only tool scope verified : {inj.read_only_scope_ok}"
          + (f" (offenders: {inj.scope_offenders})" if inj.scope_offenders else ""))
    print(f"  Attack success rate  before   : {inj.asr_before:.1f}%")
    print(f"  Attack success rate  after    : {inj.asr_after:.1f}%")
    if inj.inconclusive_count:
        print(f"  !! {inj.inconclusive_count} of "
              f"{len(inj.undefended) + len(inj.defended)} attempts were "
              f"INCONCLUSIVE (provider error). The rates above cover only "
              f"the attempts that actually ran.")
    print(f"  Availability impact rate      : {inj.availability_impact_rate:.1f}%"
          f"   (payload forced a refusal on an answerable query)")
    if inj.trajectory_pass_rate_baseline > 0:
        print(f"  Trajectory pass rate baseline : {inj.trajectory_pass_rate_baseline:.1f}%")
    else:
        print(f"  Trajectory pass rate baseline : not measured in this run")
    print(f"  Trajectory pass rate defended : {inj.trajectory_pass_rate_after_defense:.1f}%")
    print(f"  Sanitiser cost   : {inj.overhead.get('sanitize_us_per_chunk', 0):.1f} µs/chunk")
    print(f"  Guardrail cost   : {inj.overhead.get('guardrail_us_per_answer', 0):.1f} µs/answer")
    print("  Residual vulnerabilities:")
    for v in inj.residual_vulnerabilities:
        print(f"    - {v}")
    print()


def main() -> int:
    # The report uses Greek delta / micro signs; the default Windows console
    # codepage is cp1252 and would abort on them mid-table.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Week 8 trajectory evaluation suite")
    parser.add_argument("--mode", choices=["live", "offline"], default=None,
                        help="Override WEEK7_LLM_MODE for this run.")
    parser.add_argument("--provider", choices=["groq", "gemini"], default=None,
                        help="Override the LLM provider for this run.")
    parser.add_argument("--model", default=None,
                        help="Override the model id for the chosen provider.")
    parser.add_argument("--skip-injection", action="store_true",
                        help="Skip the prompt-injection bonus suite.")
    parser.add_argument("--injection-only", action="store_true",
                        help="Run only the prompt-injection bonus suite.")
    parser.add_argument(
        "--cases", default=None,
        help="Comma-separated golden-set scenario keys to run, e.g. "
             "'easy:01,hard:09'. Defaults to the standard ten. Use a short list "
             "to iterate cheaply — a full run is ~145 LLM calls.",
    )
    parser.add_argument("--json", type=str, default="trajectory_report.json",
                        help="Where to write the machine-readable report.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    output = run_trajectory_eval(
        mode=args.mode,
        provider=args.provider,
        model_override=args.model,
        include_injection=not args.skip_injection,
        injection_only=args.injection_only,
        scenario_keys=(
            tuple(k.strip() for k in args.cases.split(",") if k.strip())
            if args.cases else None
        ),
        verbose=not args.quiet,
    )
    print_report(output)

    if args.json:
        path = ROOT / args.json
        path.write_text(json.dumps(output.to_dict(), indent=2), encoding="utf-8")
        print(f"  Machine-readable report written to {path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
