"""
agent/agent_loop.py
--------------------------
Manual ReAct agent loop with visible execution trace.
Dynamically selects tools based on observations.

Two decision sources are supported (config.llm.mode):
  - "live":    the configured LLM decides each step (llm_call + parser)
  - "offline": an observation-driven OfflineReasoner decides each step,
               still reacting to real tool outputs; used for reproducible,
               API-free benchmark runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchmark.config import BenchmarkConfig
from benchmark.llm import LLMCallResult, OfflineReasoner, llm_call, REFUSAL_ANSWER
from safety.circuit_breaker import CircuitBreaker
from telemetry.telemetry import ExecutionTelemetry
from tools.reference_search import ReferenceSearchInput, reference_search
from tools.chunk_retrieval import ChunkRetrievalInput, chunk_retrieval
from tools.migration_analyzer import MigrationAnalyzerInput, migration_analyzer


# ── Trace Step ───────────────────────────────────────────────────────────────

@dataclass
class TraceStep:
    step_number: int
    decision: str
    tool: str | None = None
    tool_input: dict[str, Any] | None = None
    observation: str = ""
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step_number,
            "decision": self.decision,
            "tool": self.tool,
            "tool_input": self.tool_input,
            "observation": self.observation,
            "action": self.action,
        }


# ── Agent State ──────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    question: str
    collected_evidence: list[dict[str, Any]] = field(default_factory=list)
    search_queries_used: list[str] = field(default_factory=list)
    chunks_retrieved: list[str] = field(default_factory=list)
    is_answerable: bool = False
    answer: str = ""
    trace: list[TraceStep] = field(default_factory=list)
    tools_selected: list[str] = field(default_factory=list)


# ── Agent Prompt (live mode) ─────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """You are a ReAct agent that answers questions about GitHub REST API and Swagger Codegen documentation.

You have access to these tools:
1. reference_search - Search the reference corpus for relevant information. Params: query, version (optional).
2. chunk_retrieval - Retrieve a specific chunk by ID. Param: chunk_id.
3. migration_analyzer - Analyze retrieved evidence for a migration/comparison answer.
4. finish - Provide the final answer.

To choose the next step, output EXACTLY one action block in this simple line format
(do NOT output JSON, do NOT call any native function):

NEXT_ACTION: reference_search
QUERY: <search query>
VERSION: <optional version>

NEXT_ACTION: chunk_retrieval
CHUNK_ID: <chunk id>

NEXT_ACTION: migration_analyzer

NEXT_ACTION: finish
ANSWER: <your final grounded answer>

Rules:
- Start by searching for relevant information. If search finds nothing useful, try a different query once or twice.
- After 2-3 searches, if you still have no evidence that answers the question, finish with a refusal:
  "Information not provided in the supplied reference context."
- If retrieved chunks contain enough detail, run migration_analyzer then finish.
- NEVER fabricate. Only use what the tools returned.
- Be concise. Do not loop. Prioritise finishing once you can answer.
"""


def _parse_agent_action(llm_text: str) -> dict[str, Any]:
    """Parse the agent's line-based action block. Falls back to finish on failure."""
    text = llm_text.strip()
    action_line = None
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("NEXT_ACTION"):
            action_line = line
            break

    if action_line:
        action = action_line.split(":", 1)[1].strip().lower()
    elif any(kw in llm_text.lower() for kw in ("reference_search", "chunk_retrieval", "migration_analyzer")):
        action = "reference_search" if "reference_search" in llm_text.lower() else (
            "chunk_retrieval" if "chunk_retrieval" in llm_text.lower() else "migration_analyzer"
        )
    else:
        return {"action": "finish", "answer": llm_text, "is_answerable": False}

    params: dict[str, Any] = {"action": action}
    for line in text.splitlines():
        stripped = line.strip()
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key_lower = key.strip().upper()
            value = value.strip()
            if key_lower == "QUERY" and value:
                params["query"] = value
            elif key_lower == "VERSION" and value:
                params["version"] = value
            elif key_lower == "CHUNK_ID" and value:
                params["chunk_id"] = value
            elif key_lower == "ANSWER" and value:
                params["answer"] = value

    if action == "finish":
        params.setdefault("answer", llm_text)
        params.setdefault("is_answerable", True)
    return params


def _build_agent_prompt(
    question: str,
    state: AgentState,
    step: int,
    last_observation: str,
    max_step: int,
    empty_searches: int,
    evidence_count: int,
) -> str:
    """Build the prompt for the agent's next decision (live mode)."""
    evidence_summary = ""
    if state.collected_evidence:
        chunks = [f"[Chunk {e.get('chunk_id', '?')}]: {e.get('text', '')[:200]}" for e in state.collected_evidence[:3]]
        evidence_summary = "\n".join(chunks)

    search_hint = ""
    if empty_searches >= 2:
        search_hint = (
            "\nNOTE: Your recent searches found no relevant evidence about this question. "
            "Unless your next search surfaces clear supporting text, finish with a refusal: "
            "\"Information not provided in the supplied reference context.\""
        )
    elif evidence_count > 0 and step > 2:
        search_hint = (
            "\nNOTE: You already have evidence chunks. If they answer the question, run "
            "migration_analyzer and finish. Do not search repeatedly."
        )

    budget_note = f"You are on step {step} of a maximum of {max_step} steps."

    return f"""{AGENT_SYSTEM_PROMPT}

## Current State
{budget_note}
Question: {question}

## Previous Search Queries
{chr(10).join(state.search_queries_used) if state.search_queries_used else "None yet"}

## Chunks Retrieved
{', '.join(state.chunks_retrieved) if state.chunks_retrieved else "None yet"}

## Evidence So Far
{evidence_summary if evidence_summary else "No evidence collected yet."}

## Last Tool Observation
{last_observation if last_observation else "No previous observation."}
{search_hint}

What is your next action? Output exactly one action block in the line format shown above.
"""


# ── Agent Loop ───────────────────────────────────────────────────────────────

def run_agent(
    question: str,
    config: BenchmarkConfig,
    collection_name: str = "sdk-v3-strategy-b",
    reasoner: OfflineReasoner | None = None,
) -> tuple[AgentState, CircuitBreaker, ExecutionTelemetry]:
    """
    Execute the ReAct agent loop.
    Returns (state, circuit_breaker, telemetry) for downstream evaluation.
    """
    cb = CircuitBreaker.from_config(config.safety)
    state = AgentState(question=question)
    telemetry = ExecutionTelemetry(
        architecture="agent",
        agent_steps=[],
        tools_selected=[],
    )
    offline = config.llm.mode == "offline"
    reasoner = reasoner or OfflineReasoner(max_steps=cb.max_iterations)

    last_observation = ""
    empty_search_count = 0
    step = 0

    while not cb.any_exceeded:
        step += 1
        if not cb.step():
            break

        if offline:
            decision = reasoner.decide(
                question=question,
                evidence_count=len(state.collected_evidence),
                last_observation=last_observation,
                empty_searches=empty_search_count,
                step=step,
                chunks_retrieved=state.chunks_retrieved,
                is_answerable=state.is_answerable,
            )
            decision["action"] = decision.get("action")
            input_tokens = len(str(decision)) // 4
            output_tokens = input_tokens
            cost = cb.record_tokens(input_tokens, output_tokens)
            telemetry.input_tokens += input_tokens
            telemetry.output_tokens += output_tokens
            telemetry.estimated_cost_usd += cost
        else:
            prompt = _build_agent_prompt(
                question, state, step, last_observation,
                max_step=cb.max_iterations,
                empty_searches=empty_search_count,
                evidence_count=len(state.collected_evidence),
            )
            try:
                llm_result = llm_call(prompt, config)
                input_tokens = llm_result.input_tokens
                output_tokens = llm_result.output_tokens
                cost = cb.record_tokens(input_tokens, output_tokens)
                telemetry.input_tokens += input_tokens
                telemetry.output_tokens += output_tokens
                telemetry.estimated_cost_usd += cost
            except Exception as exc:
                trace_step = TraceStep(
                    step_number=step,
                    decision="LLM call failed",
                    observation=f"Error: {exc}",
                    action="terminate",
                )
                state.trace.append(trace_step)
                telemetry.agent_steps.append(trace_step.to_dict())
                telemetry.error = str(exc)
                break
            decision = _parse_agent_action(llm_result.text)

        action_type = decision.get("action", "finish") or "finish"

        trace_step = TraceStep(step_number=step, decision=f"Select tool: {action_type}")

        if action_type == "reference_search":
            query = decision.get("query") or question
            version = decision.get("version")

            trace_step.tool = "reference_search"
            trace_step.tool_input = {"query": query, "version": version}

            search_input = ReferenceSearchInput(query=query, version=version)
            search_result = reference_search(search_input, collection_name=collection_name)

            state.search_queries_used.append(query)
            state.collected_evidence.extend([{
                "chunk_id": r.chunk_id,
                "text": r.text,
                "source_file": r.source_file,
                "metadata": r.metadata,
            } for r in search_result.results])
            state.chunks_retrieved.extend([r.chunk_id for r in search_result.results])

            trace_step.observation = f"Found {search_result.result_count} chunks. Status: {search_result.status}"
            last_observation = trace_step.observation
            empty_search_count = empty_search_count + 1 if search_result.result_count == 0 else 0
            telemetry.tool_calls += 1
            telemetry.tools_selected.append("reference_search")

        elif action_type == "chunk_retrieval":
            chunk_id = decision.get("chunk_id", "")
            trace_step.tool = "chunk_retrieval"
            trace_step.tool_input = {"chunk_id": chunk_id}

            retrieval_input = ChunkRetrievalInput(chunk_id=chunk_id, collection_name=collection_name)
            retrieval_result = chunk_retrieval(retrieval_input)

            if retrieval_result.chunk:
                state.collected_evidence.append({
                    "chunk_id": retrieval_result.chunk.chunk_id,
                    "text": retrieval_result.chunk.text,
                    "source_file": retrieval_result.chunk.source_file,
                    "metadata": retrieval_result.chunk.metadata,
                })
                state.chunks_retrieved.append(retrieval_result.chunk.chunk_id)

            trace_step.observation = f"Retrieved chunk. Status: {retrieval_result.status}"
            last_observation = trace_step.observation
            telemetry.tool_calls += 1
            telemetry.tools_selected.append("chunk_retrieval")

        elif action_type == "migration_analyzer":
            trace_step.tool = "migration_analyzer"
            trace_step.tool_input = {"question": question}

            evidence_dicts = [{
                "chunk_id": e.get("chunk_id", ""),
                "text": e.get("text", ""),
            } for e in state.collected_evidence]

            if evidence_dicts:
                analysis_input = MigrationAnalyzerInput(
                    question=question,
                    evidence_chunks=evidence_dicts,
                )
                analysis_result = migration_analyzer(analysis_input)

                trace_step.observation = (
                    f"Analysis: is_answerable={analysis_result.is_answerable}, "
                    f"confidence={analysis_result.confidence}, "
                    f"findings={len(analysis_result.migration_changes)}"
                )
                state.is_answerable = analysis_result.is_answerable
                state.answer = analysis_result.evidence[:800]
            else:
                trace_step.observation = "No evidence to analyze"
                state.is_answerable = False

            last_observation = trace_step.observation
            telemetry.tool_calls += 1
            telemetry.tools_selected.append("migration_analyzer")

        elif action_type == "finish":
            state.answer = decision.get("answer") or REFUSAL_ANSWER
            state.is_answerable = bool(decision.get("is_answerable", False))
            trace_step.decision = "Agent decided to finish"
            trace_step.observation = f"Answer generated: {state.answer[:100]}..."
            trace_step.action = "finish"
            last_observation = trace_step.observation
            state.trace.append(trace_step)
            telemetry.agent_steps.append(trace_step.to_dict())
            break

        else:
            trace_step.observation = f"Unknown action: {action_type}"
            last_observation = trace_step.observation

        state.trace.append(trace_step)
        telemetry.agent_steps.append(trace_step.to_dict())

    if cb.any_exceeded:
        state.answer = (
            f"Information not provided in the supplied reference context. "
            f"(System terminated: {cb.exceeded_reason})"
        )
        state.is_answerable = False
        telemetry.budget_exceeded = True
        telemetry.budget_exceeded_reason = cb.exceeded_reason
        if cb.time_budget.exceeded:
            telemetry.timeout = True

    if not state.answer:
        state.answer = "Unable to generate an answer."
        state.is_answerable = False

    telemetry.iteration_count = cb.iteration_count
    telemetry.latency_ms = cb.time_budget.elapsed_ms
    telemetry.actual_behavior = "answered" if state.is_answerable else "refused"

    return state, cb, telemetry