"""
eval/trajectory_metrics.py
--------------------------
Week 8 — the trajectory metrics engine.

Turns one agent execution trace into:

  * a per-step **tool-choice** judgement (prefix automaton over the case's
    allowed path set),
  * an **argument validity** judgement per tool call (real chunk ids, real
    version strings, non-degenerate queries),
  * a **step efficiency** ratio against the case's optimal path,
  * a set of **failure-mode codes** from the taxonomy in ``trajectory_cases``.

Cost aggregation deliberately reports **p50 and Max** and never a bare mean —
a mean hides the runaway-loop tail that this whole exercise is about.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from eval.trajectory_cases import (
    ALL_MODE_CODES,
    KNOWN_TOOLS,
    VALID_VERSION_ARGS,
    TrajectoryCase,
)

# Tools that read evidence rather than produce it. Calling one of these before
# any evidence exists is an ordering failure (M2).
_EVIDENCE_CONSUMERS = frozenset({"chunk_retrieval", "migration_analyzer"})


# ─────────────────────────────────────────────────────────────────────────────
# Corpus-backed argument validation
# ─────────────────────────────────────────────────────────────────────────────

from tools.corpus_facts import (  # noqa: E402  (grouped with the other imports)
    accepted_version_values,
    corpus_chunk_ids,
    load_corpus_facts as _load_corpus_facts,
)


@dataclass
class ArgVerdict:
    valid: bool
    reason: str = ""


def validate_arguments(
    tool: str,
    tool_input: dict[str, Any] | None,
    case: TrajectoryCase,
    known_chunk_ids: frozenset[str],
    evidence_before_call: int,
    accepted_versions: frozenset[str] = frozenset(),
) -> ArgVerdict:
    """Validate one tool call's arguments against the real API surface.

    This is the "real API endpoints and version strings vs hallucinated
    parameters" check: a ``chunk_id`` that is not in the corpus, or a ``version``
    outside the corpus's metadata vocabulary, is a hallucinated parameter even
    when the surrounding answer happens to be right.
    """
    args = tool_input or {}

    if tool == "reference_search":
        query = str(args.get("query") or "").strip()
        if len(query) < 3:
            return ArgVerdict(False, f"degenerate query: {query!r}")
        version = args.get("version")
        if version not in (None, "", "null"):
            allowed = accepted_versions or VALID_VERSION_ARGS
            if str(version) not in allowed:
                return ArgVerdict(
                    False,
                    f"version={version!r} matches no sdk_version in the corpus "
                    f"(accepted: {sorted(allowed)}) — filter silently returns nothing",
                )
        return ArgVerdict(True)

    if tool == "chunk_retrieval":
        chunk_id = str(args.get("chunk_id") or "").strip()
        if not chunk_id:
            return ArgVerdict(False, "empty chunk_id")
        if known_chunk_ids and chunk_id not in known_chunk_ids:
            return ArgVerdict(False, f"chunk_id absent from corpus: {chunk_id!r}")
        return ArgVerdict(True)

    if tool == "migration_analyzer":
        if evidence_before_call <= 0:
            return ArgVerdict(False, "analyzer invoked with zero evidence chunks")
        return ArgVerdict(True)

    if tool == "finish":
        return ArgVerdict(True)

    return ArgVerdict(False, f"unknown tool: {tool!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Path-set assertion (flexible, not a rigid sequence)
# ─────────────────────────────────────────────────────────────────────────────

def valid_next_tools(case: TrajectoryCase, prefix: Sequence[str]) -> frozenset[str]:
    """Tools that keep the trajectory on at least one allowed path.

    This is the prefix automaton: given what the agent has already done, which
    next tools leave it inside the declared path set? Returns an empty set once
    the trajectory has diverged from every allowed path.
    """
    prefix = tuple(prefix)
    nxt = {
        path[len(prefix)]
        for path in case.allowed_paths
        if len(path) > len(prefix) and tuple(path[: len(prefix)]) == prefix
    }
    return frozenset(nxt)


def step_is_structurally_ok(
    case: TrajectoryCase, prefix_after: Sequence[str]
) -> bool:
    """Is this step still consistent with the case's structural contract?

    Used only once the trajectory has left every *enumerated* path. Without it,
    tool-choice accuracy and the path verdict contradict each other: an
    un-enumerated but structurally sound sequence is accepted by
    :func:`path_set_satisfied` while every step in it scores as a wrong choice.

    Checks the constraints that can be evaluated mid-run — a missing required
    tool is not a violation yet, because a later step may still supply it.
    """
    prefix_after = tuple(prefix_after)
    tool = prefix_after[-1]

    if tool not in KNOWN_TOOLS or tool in case.forbidden_tools:
        return False
    if len(prefix_after) > case.max_reasonable_steps:
        return False
    for before, after in case.ordering:
        if tool == after and before not in prefix_after[:-1]:
            return False
    return True


def path_set_satisfied(case: TrajectoryCase, actual: Sequence[str]) -> tuple[bool, str]:
    """Judge a trajectory against the case's path *set* plus its structural rules.

    A trajectory passes if it is either an enumerated allowed path, or an
    un-enumerated sequence that still honours every structural constraint
    (required tools present, forbidden tools absent, ordering respected, length
    within the reasonable ceiling). The second branch is what stops the suite
    from over-asserting on sequences we simply did not think to write down.
    """
    actual = tuple(actual)

    if actual in case.allowed_paths:
        return True, "exact match against declared path set"

    missing = case.required_tools - set(actual)
    if missing:
        return False, f"missing required tool(s): {sorted(missing)}"

    forbidden = case.forbidden_tools & set(actual)
    if forbidden:
        return False, f"used forbidden tool(s): {sorted(forbidden)}"

    unknown = set(actual) - KNOWN_TOOLS
    if unknown:
        return False, f"hallucinated tool(s): {sorted(unknown)}"

    for before, after in case.ordering:
        if before in actual and after in actual:
            if actual.index(before) > actual.index(after):
                return False, f"ordering violated: {before} must precede {after}"
        elif after in actual and before not in actual:
            return False, f"ordering violated: {after} without preceding {before}"

    if len(actual) > case.max_reasonable_steps:
        return False, (
            f"path length {len(actual)} exceeds reasonable ceiling "
            f"{case.max_reasonable_steps}"
        )

    return True, "structurally valid alternative path"


# ─────────────────────────────────────────────────────────────────────────────
# Per-run trajectory judgement
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StepJudgement:
    step: int
    tool: str
    tool_choice_ok: bool
    tool_choice_reason: str
    args_ok: bool
    args_reason: str
    tool_input: dict[str, Any] | None = None
    observation: str = ""


@dataclass
class TrajectoryJudgement:
    case_id: str
    scenario_key: str
    question: str
    actual_path: list[str] = field(default_factory=list)
    steps: list[StepJudgement] = field(default_factory=list)

    trajectory_pass: bool = False
    path_reason: str = ""

    tool_choice_accuracy: float = 0.0     # 0..1
    argument_validity_rate: float = 0.0   # 0..1
    step_efficiency: float = 0.0          # min(actual,optimal)/max(actual,optimal)
    actual_steps: int = 0
    optimal_steps: int = 0

    cost_usd: float = 0.0
    latency_ms: float = 0.0
    total_tokens: int = 0

    failure_modes: list[str] = field(default_factory=list)
    answer: str = ""

    #: Control-plane steps (mitigation gate interventions) — not tool choices.
    control_steps: int = 0
    #: Set when the run died on infrastructure (provider 429, network, crash)
    #: rather than on agent behaviour. Such a run cannot be attributed to a
    #: failure mode, so it is excluded from the taxonomy counts and reported
    #: separately instead of being silently scored as an agent mistake.
    infra_error: str | None = None

    # Filled in by the runner from the shared outcome evaluator.
    outcome_pass: bool = False
    outcome_match_type: str = ""

    @property
    def is_false_positive(self) -> bool:
        """Right answer, wrong path — the case this whole week is about.

        A run that died on infrastructure is excluded. Its "answer" is the
        loop's fallback string, which can coincidentally satisfy the outcome
        judge on a refusal case; calling that a right-answer/wrong-path result
        would credit a provider outage as an agent finding.
        """
        return (
            self.infra_error is None
            and self.outcome_pass
            and not self.trajectory_pass
        )

    @property
    def failure_reason(self) -> str:
        """Why the trajectory verdict came out the way it did.

        ``path_reason`` only reports the path-shape check. A run can walk a
        perfectly legitimate path and still fail on argument validity, so
        quoting ``path_reason`` alone produces the contradiction
        "FAIL (structurally valid alternative path)".
        """
        if self.trajectory_pass:
            return f"passed: {self.path_reason}"
        if self.infra_error:
            return self.path_reason

        reasons: list[str] = []
        ok, _ = True, None
        if "structurally valid" not in self.path_reason and "exact match" not in self.path_reason:
            reasons.append(f"path: {self.path_reason}")
        if self.argument_validity_rate < 1.0:
            bad = [s for s in self.steps if not s.args_ok]
            detail = bad[0].args_reason if bad else "invalid tool arguments"
            reasons.append(
                f"arguments: {len(bad)} of {len(bad) + sum(1 for s in self.steps if s.args_ok and s.tool != 'finish')}"
                f" tool call(s) invalid — {detail}"
            )
        if self.failure_modes:
            reasons.append(f"failure modes: {', '.join(self.failure_modes)}")
        return "; ".join(reasons) or self.path_reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scenario_key": self.scenario_key,
            "question": self.question,
            "actual_path": self.actual_path,
            "trajectory_pass": self.trajectory_pass,
            "path_reason": self.path_reason,
            "failure_reason": self.failure_reason,
            "outcome_pass": self.outcome_pass,
            "outcome_match_type": self.outcome_match_type,
            "is_false_positive": self.is_false_positive,
            "tool_choice_accuracy": round(self.tool_choice_accuracy, 4),
            "argument_validity_rate": round(self.argument_validity_rate, 4),
            "step_efficiency": round(self.step_efficiency, 4),
            "actual_steps": self.actual_steps,
            "optimal_steps": self.optimal_steps,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": round(self.latency_ms, 2),
            "total_tokens": self.total_tokens,
            "failure_modes": self.failure_modes,
            "answer": self.answer,
            "control_steps": self.control_steps,
            "infra_error": self.infra_error,
            "steps": [
                {
                    "step": s.step,
                    "tool": s.tool,
                    "tool_choice_ok": s.tool_choice_ok,
                    "tool_choice_reason": s.tool_choice_reason,
                    "args_ok": s.args_ok,
                    "args_reason": s.args_reason,
                    "tool_input": s.tool_input,
                    "observation": s.observation,
                }
                for s in self.steps
            ],
        }


def judge_trajectory(
    case: TrajectoryCase,
    agent_steps: Iterable[dict[str, Any]],
    *,
    collection_name: str,
    cost_usd: float,
    latency_ms: float,
    total_tokens: int,
    answer: str,
    budget_exceeded: bool,
    infra_error: str | None = None,
) -> TrajectoryJudgement:
    """Score one agent run's trace against its trajectory contract."""
    known_chunk_ids, accepted_versions = _load_corpus_facts(collection_name)

    judgement = TrajectoryJudgement(
        case_id=case.case_id,
        scenario_key=case.scenario_key,
        question=case.question,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        total_tokens=total_tokens,
        answer=answer,
        optimal_steps=case.optimal_steps,
        infra_error=infra_error,
    )

    prefix: list[str] = []
    correct_choices = 0
    valid_args = 0
    tool_call_count = 0
    evidence_seen = 0
    modes: set[str] = set()

    for raw in agent_steps:
        # Control-plane steps (a mitigation gate rejecting an action) are not a
        # tool choice the agent made, so they must not be scored as one. Their
        # cost still lands in the run's token/latency totals — which is exactly
        # where the mitigation's price is supposed to show up.
        if raw.get("control"):
            judgement.control_steps += 1
            continue

        tool = raw.get("tool") or ("finish" if raw.get("action") == "finish" else None)
        if tool is None:
            # A step that selected nothing concrete (parse failure / unknown
            # action). Recover the intent from the decision text.
            decision = str(raw.get("decision", ""))
            tool = decision.replace("Select tool:", "").strip() or "unknown"
            if raw.get("action") == "finish" or "finish" in decision.lower():
                tool = "finish"

        if tool not in KNOWN_TOOLS:
            modes.add("M6")

        # ── Tool choice, judged against the prefix automaton ──
        allowed_now = valid_next_tools(case, prefix)
        if allowed_now and tool in allowed_now:
            choice_ok, reason = True, "on an allowed path"
        elif step_is_structurally_ok(case, [*prefix, tool]):
            # Off the enumerated paths but still inside the contract. Scoring
            # this as a wrong choice would contradict path_set_satisfied, which
            # accepts exactly these sequences.
            choice_ok = True
            reason = "off the enumerated paths but structurally valid"
        elif allowed_now:
            choice_ok = False
            reason = f"expected one of {sorted(allowed_now)}, got {tool!r}"
        else:
            choice_ok = False
            reason = "diverged from every allowed path and breaks the contract"

        # ── Argument validity ──
        tool_input = raw.get("tool_input")
        if tool == "finish":
            args_ok, args_reason = True, ""
        else:
            tool_call_count += 1
            verdict = validate_arguments(
                tool, tool_input, case, known_chunk_ids, evidence_seen,
                accepted_versions,
            )
            args_ok, args_reason = verdict.valid, verdict.reason
            if args_ok:
                valid_args += 1
            else:
                modes.add("M3")

        if tool in _EVIDENCE_CONSUMERS and evidence_seen <= 0:
            modes.add("M2")

        if choice_ok:
            correct_choices += 1

        judgement.steps.append(
            StepJudgement(
                step=int(raw.get("step", len(judgement.steps) + 1)),
                tool=tool,
                tool_choice_ok=choice_ok,
                tool_choice_reason=reason,
                args_ok=args_ok,
                args_reason=args_reason,
                tool_input=tool_input,
                observation=str(raw.get("observation", "")),
            )
        )

        prefix.append(tool)
        if tool == "reference_search" and "Found 0 chunks" not in str(raw.get("observation", "")):
            evidence_seen += 1
        elif tool == "chunk_retrieval":
            evidence_seen += 1

    judgement.actual_path = list(prefix)
    judgement.actual_steps = len(prefix)

    total_steps = max(len(prefix), 1)
    judgement.tool_choice_accuracy = correct_choices / total_steps
    judgement.argument_validity_rate = (
        valid_args / tool_call_count if tool_call_count else 1.0
    )
    # Symmetric ratio, deliberately not `min(1.0, optimal/actual)`. Capping at
    # 1.0 scores an agent that answered from memory in a single step as
    # *perfectly efficient*, which inverts the meaning of the metric. Penalising
    # both directions means a run is efficient only when it takes roughly the
    # number of steps the task actually needs.
    _actual = max(judgement.actual_steps, 1)
    _optimal = max(case.optimal_steps, 1)
    judgement.step_efficiency = min(_actual, _optimal) / max(_actual, _optimal)

    ok, reason = path_set_satisfied(case, prefix)

    if infra_error:
        # The provider or the process died. Nothing about this run tells us
        # anything about the agent's judgement, so it gets no failure modes —
        # attributing a 429 to "the agent skipped retrieval" would be a lie.
        judgement.actual_path = list(prefix)
        judgement.failure_modes = []
        judgement.trajectory_pass = False
        judgement.path_reason = f"run aborted on infrastructure error: {infra_error}"
        return judgement

    # ── Failure-mode classification ──
    if "reference_search" not in prefix:
        modes.add("M1")
    if judgement.actual_steps > case.max_reasonable_steps:
        modes.add("M4")
    if case.kind == "comparison" and "migration_analyzer" not in prefix:
        modes.add("M5")
    if budget_exceeded:
        modes.add("M7")
    if not ok and not modes:
        # Path violated a structural rule that maps to no other mode
        # (e.g. required tool present but in the wrong order).
        modes.add("M2")

    judgement.path_reason = reason
    judgement.trajectory_pass = bool(
        ok and judgement.argument_validity_rate >= 1.0 and not modes
    )
    judgement.failure_modes = sorted(modes)
    return judgement


# ─────────────────────────────────────────────────────────────────────────────
# Suite-level aggregation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrajectoryMetrics:
    """The four telemetry dimensions, aggregated across a run."""

    label: str = ""
    total_cases: int = 0

    tool_choice_accuracy: float = 0.0      # mean over steps, 0..100
    argument_validity_rate: float = 0.0    # 0..100
    #: Mean of the per-case symmetric step ratios, 0..100. Penalises both
    #: looping and short-circuiting, so it cannot be gamed by doing less.
    step_efficiency: float = 0.0
    steps_ratio: float = 0.0               # actual/optimal, uncapped
    total_steps: int = 0
    total_optimal_steps: int = 0
    control_steps: int = 0
    errored_cases: int = 0
    scored_cases: int = 0

    # Cost is reported as p50 + Max, never a bare mean.
    cost_p50_usd: float = 0.0
    cost_max_usd: float = 0.0
    cost_total_usd: float = 0.0
    cost_max_case_id: str = ""

    latency_p50_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_max_ms: float = 0.0
    tokens_p50: float = 0.0
    tokens_max: int = 0
    tokens_total: int = 0

    outcome_pass_rate: float = 0.0
    trajectory_pass_rate: float = 0.0
    gap: float = 0.0

    failure_mode_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "total_cases": self.total_cases,
            "tool_choice_accuracy": round(self.tool_choice_accuracy, 2),
            "argument_validity_rate": round(self.argument_validity_rate, 2),
            "step_efficiency": round(self.step_efficiency, 2),
            "steps_ratio": round(self.steps_ratio, 3),
            "total_steps": self.total_steps,
            "total_optimal_steps": self.total_optimal_steps,
            "control_steps": self.control_steps,
            "errored_cases": self.errored_cases,
            "scored_cases": self.scored_cases,
            "cost_p50_usd": round(self.cost_p50_usd, 6),
            "cost_max_usd": round(self.cost_max_usd, 6),
            "cost_total_usd": round(self.cost_total_usd, 6),
            "cost_max_case_id": self.cost_max_case_id,
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p99_ms": round(self.latency_p99_ms, 2),
            "latency_max_ms": round(self.latency_max_ms, 2),
            "tokens_p50": round(self.tokens_p50, 1),
            "tokens_max": self.tokens_max,
            "tokens_total": self.tokens_total,
            "outcome_pass_rate": round(self.outcome_pass_rate, 2),
            "trajectory_pass_rate": round(self.trajectory_pass_rate, 2),
            "gap": round(self.gap, 2),
            "failure_mode_counts": self.failure_mode_counts,
        }


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Stable for the small n this suite runs at."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(pct / 100.0 * len(ordered) + 0.5)) - 1))
    return float(ordered[idx])


def aggregate(
    judgements: Sequence[TrajectoryJudgement],
    label: str = "",
) -> TrajectoryMetrics:
    """Roll per-case judgements up into the four reported dimensions."""
    metrics = TrajectoryMetrics(label=label, total_cases=len(judgements))
    if not judgements:
        metrics.failure_mode_counts = {code: 0 for code in ALL_MODE_CODES}
        return metrics

    # Tool-choice accuracy is step-weighted, not case-weighted: a 6-step run
    # that goes wrong twice should not score the same as a 2-step run that does.
    all_steps = [s for j in judgements for s in j.steps]
    correct_steps = sum(1 for s in all_steps if s.tool_choice_ok)
    metrics.tool_choice_accuracy = correct_steps / max(len(all_steps), 1) * 100

    tool_calls = [s for s in all_steps if s.tool != "finish"]
    valid_calls = sum(1 for s in tool_calls if s.args_ok)
    metrics.argument_validity_rate = valid_calls / max(len(tool_calls), 1) * 100

    metrics.total_steps = sum(j.actual_steps for j in judgements)
    metrics.total_optimal_steps = sum(j.optimal_steps for j in judgements)
    metrics.control_steps = sum(j.control_steps for j in judgements)
    metrics.errored_cases = sum(1 for j in judgements if j.infra_error)
    metrics.scored_cases = len(judgements) - metrics.errored_cases

    # Efficiency is the mean of per-case capped ratios, not a ratio of sums: a
    # run that died after one step must not register as "better than optimal"
    # and drag the fleet average above 100%.
    completed = [j for j in judgements if not j.infra_error]
    if completed:
        metrics.step_efficiency = (
            sum(j.step_efficiency for j in completed) / len(completed) * 100
        )
        metrics.steps_ratio = sum(j.actual_steps for j in completed) / max(
            sum(j.optimal_steps for j in completed), 1
        )

    costs = [j.cost_usd for j in judgements]
    metrics.cost_p50_usd = statistics.median(costs)
    metrics.cost_max_usd = max(costs)
    metrics.cost_total_usd = sum(costs)
    metrics.cost_max_case_id = max(judgements, key=lambda j: j.cost_usd).case_id

    latencies = [j.latency_ms for j in judgements]
    metrics.latency_p50_ms = statistics.median(latencies)
    metrics.latency_p99_ms = _percentile(latencies, 99)
    metrics.latency_max_ms = max(latencies)

    tokens = [float(j.total_tokens) for j in judgements]
    metrics.tokens_p50 = statistics.median(tokens)
    metrics.tokens_max = int(max(tokens))
    metrics.tokens_total = int(sum(tokens))

    metrics.outcome_pass_rate = (
        sum(1 for j in judgements if j.outcome_pass) / len(judgements) * 100
    )
    metrics.trajectory_pass_rate = (
        sum(1 for j in judgements if j.trajectory_pass) / len(judgements) * 100
    )
    metrics.gap = metrics.outcome_pass_rate - metrics.trajectory_pass_rate

    counts = {code: 0 for code in ALL_MODE_CODES}
    for j in judgements:
        for code in j.failure_modes:
            counts[code] = counts.get(code, 0) + 1
    metrics.failure_mode_counts = counts

    return metrics
