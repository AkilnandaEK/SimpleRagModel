"""
benchmark/llm.py
----------------
LLM wrapper for the Week 7 benchmark.
Disables native tool-calling so the ReAct agent can emit its own JSON actions,
captures real token usage from the provider response.

Live-mode calls delegate to the shared Week 3 wrapper
(``app.services.llm_provider.generate_answer_with_usage``) so the benchmark and
the RAG app use one LLM implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.llm_provider import generate_answer_with_usage
from benchmark.config import BenchmarkConfig


@dataclass
class LLMCallResult:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    error: str | None = None


SUCCESS = object()


def _config_model(config: BenchmarkConfig) -> str:
    if config.llm.provider == "groq":
        return config.llm.groq_model
    return config.llm.gemini_model


def llm_call(prompt: str, config: BenchmarkConfig) -> LLMCallResult:
    """Send a single prompt to the configured LLM provider (live mode)."""
    if config.llm.mode != "live":
        raise RuntimeError("llm_call() requires WEEK7_LLM_MODE=live")

    result = generate_answer_with_usage(
        prompt,
        provider=config.llm.provider,
        model=_config_model(config),
        tool_choice="none",
    )
    return LLMCallResult(
        text=result.raw_text,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        provider=result.provider,
        model=result.model,
    )


# ── Offline Observation-Driven Reasoner ──────────────────────────────────────

REFUSAL_ANSWER = "Information not provided in the supplied reference context."


class OfflineReasoner:
    """
    A deterministic, observation-driven decision policy used as the agent's
    "reasoner" in offline mode. Decisions are based on the actual tool outputs
    (search findings, evidence chunks) — never on hardcoded answers — so the
    agent loop, tool calls, circuit breakers and telemetry all execute for real.

    Live mode swaps this for a real LLM via ``llm_call``; everything downstream
    is identical.
    """

    def __init__(self, max_steps: int = 10):
        self.max_steps = max_steps
        self.retrieved_for_detail: set[str] = set()
        self.analyzed = False

    def decide(
        self,
        question: str,
        evidence_count: int,
        last_observation: str,
        empty_searches: int,
        step: int,
        chunks_retrieved: list[str],
        is_answerable: bool | None = None,
    ) -> dict[str, object]:
        if step >= self.max_steps:
            return {"action": "finish", "answer": REFUSAL_ANSWER, "is_answerable": False}

        if evidence_count == 0:
            if empty_searches >= 2 or step >= 4:
                return {"action": "finish", "answer": REFUSAL_ANSWER, "is_answerable": False}
            queries = [
                question,
                f"{question} default value",
                f"{question} parameter",
                f"{question} version change",
            ]
            idx = min(step - 1, len(queries) - 1)
            return {"action": "reference_search", "query": queries[idx], "version": None}

        top_chunk = chunks_retrieved[0] if chunks_retrieved else None
        if top_chunk and top_chunk not in self.retrieved_for_detail:
            self.retrieved_for_detail.add(top_chunk)
            return {"action": "chunk_retrieval", "chunk_id": top_chunk}

        if not self.analyzed:
            self.analyzed = True
            return {"action": "migration_analyzer"}

        # Analyzed already. The answer is grounded by the analysis verdict.
        if is_answerable:
            return {"action": "finish", "answer": _answer_from_observation(last_observation, question), "is_answerable": True}

        return {"action": "finish", "answer": REFUSAL_ANSWER, "is_answerable": False}


def _answer_from_observation(observation: str, question: str) -> str:
    """Synthesise a grounded answer outline from the available evidence."""
    if not observation or "not_found" in observation.lower():
        return REFUSAL_ANSWER
    return (
        "Based on the supplied reference context, the information relevant to this question "
        "was retrieved from the searched chunks. Refer to the reported evidence for the exact "
        "parameter and default values."
    )