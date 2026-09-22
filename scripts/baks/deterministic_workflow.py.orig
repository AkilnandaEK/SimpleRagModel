"""
workflow/deterministic_workflow.py
-----------------------------------------
Fixed, predefined sequence of operations solving the same task as the agent.
No autonomous tool-selection loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchmark.config import BenchmarkConfig
from safety.circuit_breaker import CircuitBreaker
from eval.offline_answers import synthesize_grounded_answer
from telemetry.telemetry import ExecutionTelemetry
from tools.reference_search import ReferenceSearchInput, reference_search
from tools.chunk_retrieval import ChunkRetrievalInput, chunk_retrieval
from tools.migration_analyzer import MigrationAnalyzerInput, migration_analyzer
from benchmark.llm import llm_call, REFUSAL_ANSWER


# ── Workflow State ───────────────────────────────────────────────────────────

@dataclass
class WorkflowState:
    question: str
    step_results: dict[str, Any] = field(default_factory=dict)
    answer: str = ""
    is_answerable: bool = False
    workflow_steps_completed: int = 0


# ── Workflow Steps ───────────────────────────────────────────────────────────

def _step1_search(
    question: str,
    collection_name: str,
    cb: CircuitBreaker,
) -> list[dict[str, Any]]:
    """Step 1: Search the reference corpus."""
    search_input = ReferenceSearchInput(query=question, top_k=5)
    search_result = reference_search(search_input, collection_name=collection_name)
    cb.record_tokens(len(question) // 4, search_result.result_count * 50)
    return [{
        "chunk_id": r.chunk_id,
        "text": r.text,
        "source_file": r.source_file,
        "metadata": r.metadata,
    } for r in search_result.results]


def _step2_retrieve(
    search_results: list[dict[str, Any]],
    collection_name: str,
    cb: CircuitBreaker,
) -> list[dict[str, Any]]:
    """Step 2: Retrieve full chunk content for top results."""
    retrieved = []
    for result in search_results[:3]:
        chunk_id = result.get("chunk_id", "")
        if not chunk_id:
            continue
        retrieval_input = ChunkRetrievalInput(chunk_id=chunk_id, collection_name=collection_name)
        retrieval_result = chunk_retrieval(retrieval_input)
        cb.record_tokens(len(chunk_id) // 4, 100)
        if retrieval_result.chunk:
            retrieved.append({
                "chunk_id": retrieval_result.chunk.chunk_id,
                "text": retrieval_result.chunk.text,
                "source_file": retrieval_result.chunk.source_file,
                "metadata": retrieval_result.chunk.metadata,
            })
    return retrieved if retrieved else search_results


def _step3_analyze(
    question: str,
    evidence: list[dict[str, Any]],
    cb: CircuitBreaker,
) -> tuple[bool, str]:
    """Step 3: Analyze evidence for migration/comparison findings."""
    if not evidence:
        return False, "No evidence available."

    analysis_input = MigrationAnalyzerInput(
        question=question,
        evidence_chunks=evidence,
    )
    analysis_result = migration_analyzer(analysis_input)
    cb.record_tokens(len(question) // 4, len(analysis_result.evidence) // 4)
    return analysis_result.is_answerable, analysis_result.evidence


def _step4_generate_answer(
    question: str,
    evidence: list[dict[str, Any]],
    is_answerable: bool,
    cb: CircuitBreaker,
    config: BenchmarkConfig,
) -> str:
    """Step 4: Generate final answer — grounded in evidence (LLM or offline)."""
    if not evidence or not is_answerable:
        return REFUSAL_ANSWER

    context_parts = []
    for e in evidence[:3]:
        chunk_id = e.get("chunk_id", "?")
        text = e.get("text", "")[:500]
        context_parts.append(f"[Chunk {chunk_id}]: {text}")

    context = "\n\n".join(context_parts)

    if config.llm.mode == "offline":
        cb.record_tokens(len(context) // 4, len(context) // 8)
        return (
            "Based on the supplied reference context, the information relevant to this question "
            "was retrieved from the searched chunks. Refer to the reported evidence for the exact "
            "parameter and default values."
        )

    prompt = f"""Based on the following reference document context, answer the question precisely.
If the context does not contain enough information, say "Information not provided in the supplied reference context."
Do NOT fabricate information. Only use what is in the context.

## Context
{context}

## Question
{question}

## Answer (concise, factual):
"""
    try:
        llm_result = llm_call(prompt, config)
        cb.record_tokens(llm_result.input_tokens, llm_result.output_tokens)
        return llm_result.text.strip()
    except Exception as exc:
        return f"Error generating answer: {exc}"


# ── Main Workflow ────────────────────────────────────────────────────────────

def run_workflow(
    question: str,
    config: BenchmarkConfig,
    collection_name: str = "sdk-v3-strategy-b",
) -> tuple[WorkflowState, CircuitBreaker, ExecutionTelemetry]:
    """
    Execute the deterministic workflow.
    Fixed sequence: Search → Retrieve → Analyze → Generate Answer.
    """
    cb = CircuitBreaker.from_config(config.safety)
    state = WorkflowState(question=question)
    telemetry = ExecutionTelemetry(
        architecture="workflow",
        workflow_steps=0,
    )

    # Step 1: Search
    if cb.any_exceeded:
        state.answer = "System terminated before search."
        telemetry.budget_exceeded = True
        telemetry.budget_exceeded_reason = cb.exceeded_reason
        return state, cb, telemetry

    search_results = _step1_search(question, collection_name, cb)
    state.step_results["search"] = search_results
    state.workflow_steps_completed = 1
    telemetry.workflow_steps = 1

    if not cb.step():
        state.answer = f"Budget exceeded after search: {cb.exceeded_reason}"
        telemetry.budget_exceeded = True
        telemetry.budget_exceeded_reason = cb.exceeded_reason
        return state, cb, telemetry

    # Step 2: Retrieve
    retrieved = _step2_retrieve(search_results, collection_name, cb)
    state.step_results["retrieve"] = retrieved
    state.workflow_steps_completed = 2
    telemetry.workflow_steps = 2

    if not cb.step():
        state.answer = f"Budget exceeded after retrieval: {cb.exceeded_reason}"
        telemetry.budget_exceeded = True
        telemetry.budget_exceeded_reason = cb.exceeded_reason
        return state, cb, telemetry

    # Step 3: Analyze
    is_answerable, evidence_text = _step3_analyze(question, retrieved, cb)
    state.step_results["analyze"] = {"is_answerable": is_answerable, "evidence": evidence_text}
    state.workflow_steps_completed = 3
    telemetry.workflow_steps = 3

    if not cb.step():
        state.answer = f"Budget exceeded after analysis: {cb.exceeded_reason}"
        telemetry.budget_exceeded = True
        telemetry.budget_exceeded_reason = cb.exceeded_reason
        return state, cb, telemetry

    # Step 4: Generate answer
    state.answer = _step4_generate_answer(question, retrieved, is_answerable, cb, config)
    state.is_answerable = is_answerable
    state.workflow_steps_completed = 4
    telemetry.workflow_steps = 4

    telemetry.latency_ms = cb.time_budget.elapsed_ms
    telemetry.iteration_count = cb.iteration_count
    telemetry.tool_calls = 3  # search + retrieve + analyze
    telemetry.input_tokens = cb.token_budget.input_tokens
    telemetry.output_tokens = cb.token_budget.output_tokens
    telemetry.total_tokens = cb.token_budget.total_tokens
    telemetry.estimated_cost_usd = cb.cost_budget.spent_usd
    telemetry.actual_behavior = "answered" if state.is_answerable else "refused"

    if cb.any_exceeded and cb.exceeded_reason:
        telemetry.budget_exceeded = True
        telemetry.budget_exceeded_reason = cb.exceeded_reason
        if cb.time_budget.exceeded:
            telemetry.timeout = True

    return state, cb, telemetry