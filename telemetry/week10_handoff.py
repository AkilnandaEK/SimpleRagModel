"""
telemetry/week10_handoff.py
------------------------------
Minimal, Week 10-specific handoff telemetry.

Scope
-----
``telemetry/telemetry.py`` models a *run* (``ExecutionTelemetry``), and
``eval/benchmark_runner.py`` aggregates tokens as ``input_tokens +
output_tokens`` per run, joined by ``run_id``/``trace_id``. A Week 10 squad
run is made of several agent-to-agent handoffs, and each handoff needs its own
source/destination/latency record. Forcing handoff rows into
``ExecutionTelemetry`` would change the existing run-level schema and its
aggregation path, so this module adds a small dedicated record type instead.

It is deliberately *not* a second general telemetry framework: it only models
one thing — a single Orchestrator -> Worker delegation — and reuses the field
names and ``to_dict()`` convention already established by the project.

Token honesty
-------------
Token counts are **never estimated or invented here**. A worker's token fields
are populated only from real usage produced by the LLM/tool execution path
(``benchmark.llm.llm_call`` -> ``LLMCallResult.input_tokens/output_tokens``).

Workers that execute without any LLM call have no provider token usage. Those
records carry ``input_tokens=None``/``output_tokens=None`` and
``token_source="unavailable"`` rather than a fabricated zero. That distinction
propagates into :class:`HandoffTokenSummary.tokens_complete` so an external
race runner can tell a real measurement from an incomplete one before dividing
into the Context Re-Send Multiplier.

Two distinct measurements
-------------------------
These are deliberately separate fields and must never be summed together:

1. ``input_tokens`` / ``output_tokens`` — **LLM/provider token usage.** Real
   counts only, from ``benchmark.llm.llm_call`` -> ``LLMCallResult``. ``None``
   when no LLM call happened.

2. ``handoff_context_tokens`` — **agent-to-agent context re-send.** Size of the
   textual context that physically crossed the Orchestrator -> Worker boundary
   (the question, plus evidence text forwarded between workers). This is a
   property of the payload, not of any model, so it is well-defined even when
   the destination worker never calls an LLM.

The context figure uses the project's existing offline convention
(``len(text) // 4``) because that is how the Single Agent already reports
tokens -- see :func:`project_chars_div_4`. It is a character heuristic, not a
real BPE tokenization, and is flagged as such via
``context_token_method``/``context_tokens_estimated``. Using a real tokenizer
here while the Single Agent stays on ``//4`` would compare mismatched units and
make the Context Re-Send Multiplier meaningless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

#: Token counts came from real provider/execution reporting.
TOKEN_SOURCE_MEASURED = "measured"

#: No LLM call was made, so no token usage exists to report. Never coerced to 0.
TOKEN_SOURCE_UNAVAILABLE = "unavailable"

#: Context size measured with the project's existing ``len(text) // 4`` heuristic.
CONTEXT_TOKEN_METHOD_CHARS_DIV_4 = "project_chars_div_4"

#: Context size measured with a real tokenizer.
CONTEXT_TOKEN_METHOD_REAL_TOKENIZER = "real_tokenizer"


def project_chars_div_4(text: str) -> int:
    """Count context tokens the way this project already counts them offline.

    Matches the convention used by ``agent/agent_loop.py`` (``len(str(decision)) // 4``),
    ``workflow/deterministic_workflow.py`` and the ``app/services/llm_provider.py``
    fallback. Chosen deliberately so the Context Re-Send Multiplier compares
    like with like against the untouched Single Agent totals.
    """
    if not text:
        return 0
    return len(text) // 4


#: Callable ``(text) -> int``. Swappable so a real tokenizer can replace the
#: heuristic later without touching call sites.
ContextTokenCounter = Callable[[str], int]


def count_context_tokens(parts: list[str], counter: ContextTokenCounter) -> int:
    """Total context tokens across payload parts, counting empty parts as zero."""
    return sum(counter(part) for part in parts if part)


@dataclass
class HandoffTelemetry:
    """One observable Orchestrator -> Worker delegation."""

    #: Joins to ``ExecutionTelemetry.run_id`` (``trace_id``) for the same run.
    run_id: str = ""
    #: Monotonic position of this handoff within the run (0-based).
    sequence: int = 0
    source_agent: str = ""
    destination_agent: str = ""
    #: Short task identifier, e.g. "version_deprecation_analysis".
    task: str = ""
    #: Stable per-handoff identifier; ``f"{run_id}:{sequence}:{task}"``.
    task_id: str = ""
    #: The question text that drove the delegation.
    question: str = ""
    #: Real input tokens, or ``None`` when no LLM call produced a measurement.
    input_tokens: int | None = None
    #: Real output tokens, or ``None`` when no LLM call produced a measurement.
    output_tokens: int | None = None
    #: Wall-clock elapsed execution time around the delegation.
    latency_ms: float = 0.0
    success: bool = False
    error: str | None = None
    #: ``"measured"`` or ``"unavailable"`` — see module docstring.
    token_source: str = TOKEN_SOURCE_UNAVAILABLE
    # ── Context re-send (distinct from provider tokens above) ──
    #: Context tokens that crossed this agent boundary. Independent of any LLM call.
    handoff_context_tokens: int = 0
    #: How ``handoff_context_tokens`` was derived.
    context_token_method: str = CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    #: True when the count came from a character heuristic rather than a real tokenizer.
    context_tokens_estimated: bool = True
    llm_calls: int = 0
    tool_calls: int = 0
    #: Per-handoff detail bag (collection name, refusal flags, ...).
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int | None:
        """Sum of measured tokens, or ``None`` when unmeasured.

        Deliberately *not* ``0``: a missing measurement must stay distinguishable
        from a genuinely free delegation.
        """
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    @property
    def tokens_available(self) -> bool:
        return self.token_source == TOKEN_SOURCE_MEASURED

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "source_agent": self.source_agent,
            "destination_agent": self.destination_agent,
            "task": self.task,
            "task_id": self.task_id,
            "question": self.question,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": round(self.latency_ms, 2),
            "success": self.success,
            "error": self.error,
            "token_source": self.token_source,
            "tokens_available": self.tokens_available,
            "handoff_context_tokens": self.handoff_context_tokens,
            "context_token_method": self.context_token_method,
            "context_tokens_estimated": self.context_tokens_estimated,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "details": self.details,
        }


@dataclass
class HandoffTokenSummary:
    """Run-level token rollup an external race runner can aggregate directly.

    Mirrors ``BenchmarkMetrics.total_tokens`` in ``eval/benchmark_runner.py``
    so the Week 10 race can compute::

        Multi-Agent Total Tokens      = summary.measured_total_tokens
        Context Re-Send Multiplier    = multi_agent_total / single_agent_total

    ``tokens_complete`` is the guard rail: when it is ``False`` at least one
    handoff had no measurable token usage, so the multiplier numerator is a
    floor rather than a complete measurement and should be reported as such.
    """

    measured_input_tokens: int = 0
    measured_output_tokens: int = 0
    measured_total_tokens: int = 0
    handoff_count: int = 0
    measured_handoff_count: int = 0
    unavailable_handoff_count: int = 0
    #: True only when every handoff carried real measured token usage.
    tokens_complete: bool = True
    # ── Context re-send (numerator for the Context Re-Send Multiplier) ──
    #: Sum of ``handoff_context_tokens`` across all handoffs in the run.
    total_context_tokens: int = 0
    context_token_method: str = CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    context_tokens_estimated: bool = True

    def context_resend_multiplier(self, single_agent_total_tokens: int) -> float | None:
        """``Multi-Agent Total Tokens / Single Agent Total Tokens``.

        Uses ``total_context_tokens`` (agent-to-agent re-send) and never mixes
        in provider tokens, so the two measurement kinds cannot double-count.
        Returns ``None`` when the denominator is unusable (missing or zero)
        rather than fabricating an infinite or zero multiplier.
        """
        if single_agent_total_tokens is None or single_agent_total_tokens <= 0:
            return None
        return self.total_context_tokens / single_agent_total_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured_input_tokens": self.measured_input_tokens,
            "measured_output_tokens": self.measured_output_tokens,
            "measured_total_tokens": self.measured_total_tokens,
            "handoff_count": self.handoff_count,
            "measured_handoff_count": self.measured_handoff_count,
            "unavailable_handoff_count": self.unavailable_handoff_count,
            "tokens_complete": self.tokens_complete,
            "total_context_tokens": self.total_context_tokens,
            "context_token_method": self.context_token_method,
            "context_tokens_estimated": self.context_tokens_estimated,
        }


def aggregate_handoff_tokens(
    telemetries: list[HandoffTelemetry],
) -> HandoffTokenSummary:
    """Sum only real measurements and report how many were unavailable."""
    measured = [t for t in telemetries if t.tokens_available]
    unavailable = [t for t in telemetries if not t.tokens_available]

    measured_input = sum(int(t.input_tokens or 0) for t in measured)
    measured_output = sum(int(t.output_tokens or 0) for t in measured)
    total_context = sum(int(t.handoff_context_tokens or 0) for t in telemetries)

    methods = {t.context_token_method for t in telemetries}
    method = methods.pop() if len(methods) == 1 else "mixed"

    return HandoffTokenSummary(
        measured_input_tokens=measured_input,
        measured_output_tokens=measured_output,
        measured_total_tokens=measured_input + measured_output,
        handoff_count=len(telemetries),
        measured_handoff_count=len(measured),
        unavailable_handoff_count=len(unavailable),
        tokens_complete=not unavailable,
        total_context_tokens=total_context,
        context_token_method=method,
        context_tokens_estimated=any(t.context_tokens_estimated for t in telemetries),
    )


def build_task_id(run_id: str, sequence: int, task: str) -> str:
    """Stable identifier for a single handoff within a run."""
    return f"{run_id}:{sequence}:{task}"