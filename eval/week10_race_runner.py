"""
eval/week10_race_runner.py
------------------------------
Week 10 head-to-head race: existing Single Agent vs. the Week 10 Manager squad.

Both arms run the *same* 10 Week-6 golden cases, through the *same* corpus and
the *same* evaluator (``eval.evaluator.evaluate_answer``). No second evaluator
exists, and neither arm gets special correctness criteria.

Fairness rules enforced here
----------------------------
* One shared selection of golden entries; both arms iterate that identical
  list. Neither arm can receive extra cases.
* Arm A calls ``agent.agent_loop.run_agent`` unchanged. Its token accounting,
  latency measurement and evaluation are not touched.
* Arm B calls the Week 10 ``ManagerOrchestrator``.
* Golden-set expectations are never mutated.
* No case-specific tuning of either arm.

Token accounting (two distinct concepts, never conflated)
----------------------------------------------------------
``provider_total_tokens``
    Real LLM/provider usage. Arm A reports its own existing numbers.
    Arm B reports ``None`` because the Week 10 workers make no LLM call --
    ``None`` is never coerced to 0.

``total_context_tokens``
    Agent-to-agent context re-send for Arm B, measured with the already
    implemented ``project_chars_div_4`` convention. This is an *estimate*
    (character heuristic), not model-native BPE usage, and is labelled as such
    via ``context_token_method`` / ``context_tokens_estimated``.

A note on cost: Arm B genuinely costs $0.00 in provider fees because it makes no
API calls (retrieval and embeddings are local). That is a real cost of 0, and
it is deliberately reported *alongside* the context-token figure so the two are
never confused with one another.

This module does not generate Markdown or log artifacts.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.agent_loop import run_agent
from agent.multi_agent import ManagerOrchestrator, SquadRequest
from benchmark.config import BenchmarkConfig
from eval.benchmark_runner import _expand_scenario_keys, _warmup
from eval.evaluator import EvalResult, evaluate_answer
from eval.golden_loader import (
    GoldenEntry,
    get_all_entries,
    load_all_golden_sets,
)
from telemetry.telemetry import ExecutionTelemetry
from telemetry.week10_handoff import (
    CONTEXT_TOKEN_METHOD_CHARS_DIV_4,
    HandoffTelemetry,
)

#: The exact 10 Week-6 evaluation cases both arms must run.
WEEK10_CASE_IDS: list[str] = [
    "easy:01",
    "easy:04",
    "easy:13",
    "medium:02",
    "medium:05",
    "medium:14",
    "hard:01",
    "hard:04",
    "hard:09",
    "hard:13",
]

ARM_SINGLE = "single_agent"
ARM_MULTI = "multi_agent"


# ── Injection hooks (defaults are the real production paths) ───────────────


def _default_single_runner(
    question: str, config: BenchmarkConfig, collection_name: str
) -> tuple[Any, Any, ExecutionTelemetry]:
    """Arm A: the existing Single Agent, unmodified."""
    return run_agent(question, config, collection_name)


def _default_multi_runner(
    question: str, config: BenchmarkConfig, collection_name: str
) -> Any:
    """Arm B: the Week 10 Manager + two specialists."""
    orchestrator = ManagerOrchestrator(lambda: collection_name)
    return orchestrator.run(
        SquadRequest(
            question=question,
            config=config,
            collection_name=collection_name,
        )
    )


# ── Result model ───────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    """Raw per-case result for one arm. Nothing is pre-aggregated here."""

    case_id: str
    arm: str
    level: str
    question: str
    is_correct: bool
    match_type: str
    answer: str
    latency_ms: float
    error: str | None = None
    #: Real provider tokens, or ``None`` when no LLM call was made.
    provider_input_tokens: int | None = None
    provider_output_tokens: int | None = None
    cost_usd: float = 0.0
    # ── Multi-agent handoff fields ──
    handoff_count: int = 0
    successful_handoffs: int = 0
    failed_handoffs: int = 0
    handoff_errors: list[str] = field(default_factory=list)
    total_context_tokens: int = 0
    context_token_method: str = CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    context_tokens_estimated: bool = True
    #: Full per-handoff telemetry, preserved verbatim for later artifacts.
    handoff_telemetry: list[dict[str, Any]] = field(default_factory=list)
    #: Worker execution info (tool calls per handoff).
    worker_tool_calls: int = 0
    worker_llm_calls: int = 0

    @property
    def provider_total_tokens(self) -> int | None:
        """``None`` when tokens were never measured -- never coerced to 0."""
        if self.provider_input_tokens is None or self.provider_output_tokens is None:
            return None
        return self.provider_input_tokens + self.provider_output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "arm": self.arm,
            "level": self.level,
            "question": self.question,
            "is_correct": self.is_correct,
            "match_type": self.match_type,
            "answer": self.answer,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "provider_input_tokens": self.provider_input_tokens,
            "provider_output_tokens": self.provider_output_tokens,
            "provider_total_tokens": self.provider_total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "handoff_count": self.handoff_count,
            "successful_handoffs": self.successful_handoffs,
            "failed_handoffs": self.failed_handoffs,
            "handoff_errors": list(self.handoff_errors),
            "total_context_tokens": self.total_context_tokens,
            "context_token_method": self.context_token_method,
            "context_tokens_estimated": self.context_tokens_estimated,
            "handoff_telemetry": list(self.handoff_telemetry),
            "worker_tool_calls": self.worker_tool_calls,
            "worker_llm_calls": self.worker_llm_calls,
        }


@dataclass
class ArmMetrics:
    """Aggregates computed only from actual per-case results."""

    arm: str
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    #: Percentage of cases the shared evaluator marked correct.
    pass_rate: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    #: Sum of real provider tokens, or ``None`` if never measured.
    provider_total_tokens: int | None = 0
    provider_tokens_available: bool = True
    #: Sum of agent-to-agent context re-send tokens (multi-agent arm).
    total_context_tokens: int = 0
    context_token_method: str = CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    context_tokens_estimated: bool = True
    total_cost_usd: float = 0.0
    cost_per_question_usd: float = 0.0
    total_handoffs: int = 0
    successful_handoffs: int = 0
    failed_handoffs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 2),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "provider_total_tokens": self.provider_total_tokens,
            "provider_tokens_available": self.provider_tokens_available,
            "total_context_tokens": self.total_context_tokens,
            "context_token_method": self.context_token_method,
            "context_tokens_estimated": self.context_tokens_estimated,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "cost_per_question_usd": round(self.cost_per_question_usd, 6),
            "total_handoffs": self.total_handoffs,
            "successful_handoffs": self.successful_handoffs,
            "failed_handoffs": self.failed_handoffs,
        }


@dataclass
class MultiAgentHandoffSummary:
    """Handoff/context rollup across every multi-agent case."""

    total_handoffs: int = 0
    successful_handoffs: int = 0
    failed_handoffs: int = 0
    by_destination: dict[str, dict[str, int]] = field(default_factory=dict)
    total_context_tokens: int = 0
    context_token_method: str = CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    context_tokens_estimated: bool = True
    provider_tokens_available: bool = False
    provider_token_note: str = (
        "Week 10 workers make no LLM call, so provider token usage is "
        "unavailable (None) and is never reported as 0."
    )
    context_token_note: str = (
        "total_context_tokens is agent-to-agent context re-send measured with "
        "project_chars_div_4 (len(text)//4). It is an ESTIMATE derived from "
        "characters, not model-native BPE tokenization."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_handoffs": self.total_handoffs,
            "successful_handoffs": self.successful_handoffs,
            "failed_handoffs": self.failed_handoffs,
            "by_destination": self.by_destination,
            "total_context_tokens": self.total_context_tokens,
            "context_token_method": self.context_token_method,
            "context_tokens_estimated": self.context_tokens_estimated,
            "provider_tokens_available": self.provider_tokens_available,
            "provider_token_note": self.provider_token_note,
            "context_token_note": self.context_token_note,
        }


@dataclass
class RaceResult:
    case_ids: list[str] = field(default_factory=list)
    single_agent_cases: list[CaseResult] = field(default_factory=list)
    multi_agent_cases: list[CaseResult] = field(default_factory=list)
    single_agent_metrics: ArmMetrics = field(default_factory=lambda: ArmMetrics(arm=ARM_SINGLE))
    multi_agent_metrics: ArmMetrics = field(default_factory=lambda: ArmMetrics(arm=ARM_MULTI))
    multi_agent_handoffs: MultiAgentHandoffSummary = field(
        default_factory=MultiAgentHandoffSummary
    )
    #: Always False for the clean baseline race.
    failure_injection_enabled: bool = False

    def context_resend_multiplier(self, single_agent_provider_tokens: int | None) -> float | None:
        """Multi-Agent context re-send / Single Agent provider tokens.

        Returns ``None`` when the denominator is unusable rather than
        fabricating an infinite or zero value.
        """
        if not single_agent_provider_tokens or single_agent_provider_tokens <= 0:
            return None
        return self.multi_agent_handoffs.total_context_tokens / single_agent_provider_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_ids": list(self.case_ids),
            "failure_injection_enabled": self.failure_injection_enabled,
            "single_agent_cases": [c.to_dict() for c in self.single_agent_cases],
            "multi_agent_cases": [c.to_dict() for c in self.multi_agent_cases],
            "single_agent_metrics": self.single_agent_metrics.to_dict(),
            "multi_agent_metrics": self.multi_agent_metrics.to_dict(),
            "multi_agent_handoffs": self.multi_agent_handoffs.to_dict(),
            "context_resend_multiplier": self.context_resend_multiplier(
                self.single_agent_metrics.provider_total_tokens
            ),
        }


# ── Aggregation ────────────────────────────────────────────────────────────


def _percentile_nearest_rank(values: list[float], pct: float) -> float:
    """Nearest-rank percentile: index = ceil(pct/100 * n) - 1."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, math.ceil(pct / 100.0 * len(ordered)) - 1)
    return ordered[idx]


def _compute_arm_metrics(arm: str, cases: list[CaseResult]) -> ArmMetrics:
    """Build aggregates purely from the recorded per-case results."""
    if not cases:
        return ArmMetrics(arm=arm)

    passed = sum(1 for c in cases if c.is_correct)
    latencies = [c.latency_ms for c in cases]
    total_cost = sum(c.cost_usd for c in cases)

    measured = [c for c in cases if c.provider_total_tokens is not None]
    provider_total = (
        sum(int(c.provider_total_tokens) for c in measured) if len(measured) == len(cases) else None
    )

    return ArmMetrics(
        arm=arm,
        total_cases=len(cases),
        passed=passed,
        failed=len(cases) - passed,
        pass_rate=passed / len(cases) * 100,
        p50_latency_ms=statistics.median(latencies),
        p99_latency_ms=_percentile_nearest_rank(latencies, 99),
        provider_total_tokens=provider_total,
        provider_tokens_available=provider_total is not None,
        total_context_tokens=sum(c.total_context_tokens for c in cases),
        total_cost_usd=total_cost,
        cost_per_question_usd=total_cost / len(cases),
        total_handoffs=sum(c.handoff_count for c in cases),
        successful_handoffs=sum(c.successful_handoffs for c in cases),
        failed_handoffs=sum(c.failed_handoffs for c in cases),
    )


def _build_handoff_summary(cases: list[CaseResult]) -> MultiAgentHandoffSummary:
    summary = MultiAgentHandoffSummary()
    for case in cases:
        summary.total_handoffs += case.handoff_count
        summary.successful_handoffs += case.successful_handoffs
        summary.failed_handoffs += case.failed_handoffs
        summary.total_context_tokens += case.total_context_tokens
        for record in case.handoff_telemetry:
            dest = record.get("destination_agent", "unknown")
            bucket = summary.by_destination.setdefault(
                dest, {"total": 0, "success": 0, "failed": 0, "context_tokens": 0}
            )
            bucket["total"] += 1
            bucket["success" if record.get("success") else "failed"] += 1
            bucket["context_tokens"] += int(record.get("handoff_context_tokens", 0) or 0)
    return summary


# ── Per-arm execution ──────────────────────────────────────────────────────


def _run_single_arm(
    entry: GoldenEntry,
    config: BenchmarkConfig,
    collection_name: str,
    runner: Callable[..., Any],
) -> CaseResult:
    """Run Arm A and score it with the shared evaluator.

    The returned ``ExecutionTelemetry`` is the Single Agent's own object with
    its own token accounting, untouched.
    """
    case_id = f"{entry.level.lower()}:{entry.id}"
    try:
        state, _cb, tel = runner(entry.question, config, collection_name)
        evaluation = evaluate_answer(entry, state.answer, tel)
        return CaseResult(
            case_id=case_id,
            arm=ARM_SINGLE,
            level=entry.level,
            question=entry.question,
            is_correct=evaluation.is_correct,
            match_type=evaluation.match_type,
            answer=state.answer,
            # Single Agent's own latency measurement, unchanged.
            latency_ms=tel.latency_ms,
            error=tel.error,
            provider_input_tokens=tel.input_tokens,
            provider_output_tokens=tel.output_tokens,
            cost_usd=tel.estimated_cost_usd,
        )
    except Exception as exc:
        evaluation = _crash_eval(entry, exc, ARM_SINGLE)
        return CaseResult(
            case_id=case_id,
            arm=ARM_SINGLE,
            level=entry.level,
            question=entry.question,
            is_correct=False,
            match_type=evaluation.match_type,
            answer="",
            latency_ms=0.0,
            error=str(exc),
            provider_input_tokens=None,
            provider_output_tokens=None,
            cost_usd=0.0,
        )


def _run_multi_arm(
    entry: GoldenEntry,
    config: BenchmarkConfig,
    collection_name: str,
    runner: Callable[..., Any],
) -> CaseResult:
    """Run Arm B and score it with the shared evaluator."""
    case_id = f"{entry.level.lower()}:{entry.id}"
    try:
        response = runner(entry.question, config, collection_name)
    except Exception as exc:
        evaluation = _crash_eval(entry, exc, ARM_MULTI)
        return CaseResult(
            case_id=case_id,
            arm=ARM_MULTI,
            level=entry.level,
            question=entry.question,
            is_correct=False,
            match_type=evaluation.match_type,
            answer="",
            latency_ms=0.0,
            error=str(exc),
            provider_input_tokens=None,
            provider_output_tokens=None,
            cost_usd=0.0,
        )

    # The evaluator requires an ExecutionTelemetry carrier. It reads no token
    # field from it, so it is used purely to satisfy the shared interface.
    # Provider token truth for this arm lives in the handoff telemetry below,
    # where unavailability is modelled as None rather than 0.
    carrier = ExecutionTelemetry(
        architecture=ARM_MULTI,
        scenario_id=entry.id,
        difficulty=entry.level,
        is_negative_case=entry.is_negative_case,
        expected_behavior=entry.expected_behavior or "answer_correctly",
        latency_ms=response.latency_ms,
        answer=response.answer,
    )
    evaluation = evaluate_answer(entry, response.answer, carrier)

    records: list[dict[str, Any]] = [t.to_dict() for t in response.handoff_telemetry]
    summary = response.token_summary

    # Provider tokens: unavailable, because no worker made an LLM call.
    provider_in: int | None = None
    provider_out: int | None = None
    if summary.tokens_complete and summary.measured_handoff_count > 0:
        provider_in = summary.measured_input_tokens
        provider_out = summary.measured_output_tokens

    return CaseResult(
        case_id=case_id,
        arm=ARM_MULTI,
        level=entry.level,
        question=entry.question,
        is_correct=evaluation.is_correct,
        match_type=evaluation.match_type,
        answer=response.answer,
        latency_ms=response.latency_ms,
        error="; ".join(response.errors) if response.errors else None,
        provider_input_tokens=provider_in,
        provider_output_tokens=provider_out,
        cost_usd=carrier.estimated_cost_usd,
        handoff_count=len(response.handoff_telemetry),
        successful_handoffs=sum(1 for t in response.handoff_telemetry if t.success),
        failed_handoffs=sum(1 for t in response.handoff_telemetry if not t.success),
        handoff_errors=[
            f"{t.source_agent}->{t.destination_agent}: {t.error}"
            for t in response.handoff_telemetry
            if not t.success and t.error
        ],
        total_context_tokens=summary.total_context_tokens,
        context_token_method=summary.context_token_method,
        context_tokens_estimated=summary.context_tokens_estimated,
        handoff_telemetry=records,
        worker_tool_calls=sum(int(t.tool_calls) for t in response.handoff_telemetry),
        worker_llm_calls=sum(int(t.llm_calls) for t in response.handoff_telemetry),
    )


def _crash_eval(entry: GoldenEntry, exc: Exception, arm: str) -> EvalResult:
    """Score an arm that crashed as incorrect, via the shared evaluator types."""
    tel = ExecutionTelemetry(
        architecture=arm,
        scenario_id=entry.id,
        difficulty=entry.level,
        error=str(exc),
        answer="",
    )
    return EvalResult(
        scenario_id=entry.id,
        level=entry.level,
        is_correct=False,
        match_type="incorrect",
        details=f"{arm} crashed: {exc}",
        telemetry=tel,
    )


# ── Selection ──────────────────────────────────────────────────────────────


def select_week10_cases(
    config: BenchmarkConfig, case_ids: list[str] | None = None
) -> list[GoldenEntry]:
    """Resolve the fixed 10-case selection, reusing the existing key expansion.

    Raises if any requested case does not resolve to exactly one golden entry,
    so the two arms can never silently diverge.
    """
    keys = list(case_ids) if case_ids is not None else list(WEEK10_CASE_IDS)
    all_sets = load_all_golden_sets(config.golden_set_dir)
    entries = get_all_entries(all_sets)

    selected = _expand_scenario_keys(entries, keys)

    expected = len(keys)
    if len(selected) != expected:
        raise ValueError(
            f"Week 10 race expects {expected} cases, resolved {len(selected)}"
        )

    # Preserve the declared order so both arms run the identical sequence.
    by_key = {f"{e.level.lower()}:{e.id}": e for e in selected}
    ordered: list[GoldenEntry] = []
    for key in keys:
        normalized = key.strip().lower()
        if normalized not in by_key:
            raise ValueError(f"Case '{key}' did not resolve to a golden entry")
        ordered.append(by_key[normalized])
    return ordered


# ── Entry point ────────────────────────────────────────────────────────────


def run_week10_race(
    config: BenchmarkConfig,
    case_ids: list[str] | None = None,
    verbose: bool = False,
    single_runner: Callable[..., Any] = _default_single_runner,
    multi_runner: Callable[..., Any] = _default_multi_runner,
) -> RaceResult:
    """Run the clean baseline head-to-head race.

    Both arms iterate the same ordered entry list, receive the same question
    text, and are scored by ``eval.evaluator.evaluate_answer``. No failure
    injection is active.
    """
    entries = select_week10_cases(config, case_ids)
    collection_name = config.retrieval.collection_name

    if verbose:
        print(f"[week10] warming up (embedding + Chroma) for {len(entries)} cases")
    _warmup(config)

    result = RaceResult(
        case_ids=[f"{e.level.lower()}:{e.id}" for e in entries],
        failure_injection_enabled=False,
    )

    for entry in entries:
        case_id = f"{entry.level.lower()}:{entry.id}"
        if verbose:
            print(f"\n[week10] {case_id}")

        single_case = _run_single_arm(entry, config, collection_name, single_runner)
        multi_case = _run_multi_arm(entry, config, collection_name, multi_runner)

        result.single_agent_cases.append(single_case)
        result.multi_agent_cases.append(multi_case)

        if verbose:
            print(
                f"   single: correct={single_case.is_correct} "
                f"latency={single_case.latency_ms:.0f}ms"
            )
            print(
                f"   multi : correct={multi_case.is_correct} "
                f"latency={multi_case.latency_ms:.0f}ms "
                f"ctx_tokens={multi_case.total_context_tokens}"
            )

    result.single_agent_metrics = _compute_arm_metrics(ARM_SINGLE, result.single_agent_cases)
    result.multi_agent_metrics = _compute_arm_metrics(ARM_MULTI, result.multi_agent_cases)
    result.multi_agent_handoffs = _build_handoff_summary(result.multi_agent_cases)

    return result


def format_race_summary(result: RaceResult) -> str:
    """Plain-text console summary. No files are written."""
    sa = result.single_agent_metrics
    ma = result.multi_agent_metrics
    h = result.multi_agent_handoffs

    lines = [
        "Week 10 Head-to-Head Race (clean baseline, no failure injection)",
        f"Cases: {len(result.case_ids)} -> {', '.join(result.case_ids)}",
        "",
        f"{'metric':34s} {'single_agent':>16s} {'multi_agent':>16s}",
        f"{'pass_rate %':34s} {sa.pass_rate:>16.2f} {ma.pass_rate:>16.2f}",
        f"{'p50_latency_ms':34s} {sa.p50_latency_ms:>16.2f} {ma.p50_latency_ms:>16.2f}",
        f"{'p99_latency_ms':34s} {sa.p99_latency_ms:>16.2f} {ma.p99_latency_ms:>16.2f}",
        f"{'provider_total_tokens':34s} {str(sa.provider_total_tokens):>16s} {str(ma.provider_total_tokens):>16s}",
        f"{'total_context_tokens':34s} {'n/a':>16s} {h.total_context_tokens:>16d}",
        f"{'cost_per_question_usd':34s} {sa.cost_per_question_usd:>16.6f} {ma.cost_per_question_usd:>16.6f}",
        "",
        f"context_token_method      : {h.context_token_method} (estimated={h.context_tokens_estimated})",
        f"handoffs total/success/fail: {h.total_handoffs}/{h.successful_handoffs}/{h.failed_handoffs}",
        f"multi provider tokens    : {h.provider_token_note}",
        f"multi context tokens     : {h.context_token_note}",
    ]
    return "\n".join(lines)