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

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from benchmark.config import BenchmarkConfig
from benchmark.llm import LLMCallResult, OfflineReasoner, llm_call, REFUSAL_ANSWER
from safety.circuit_breaker import CircuitBreaker
from telemetry.telemetry import ExecutionTelemetry
from tools.corpus_facts import accepted_version_values
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
    #: True for control-plane steps (e.g. a mitigation gate rejecting an action)
    #: rather than a tool selection. Trajectory scoring skips these — they are
    #: not a tool choice the agent made, they are the harness correcting it.
    control: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step_number,
            "decision": self.decision,
            "tool": self.tool,
            "tool_input": self.tool_input,
            "observation": self.observation,
            "action": self.action,
            "control": self.control,
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


#: Actions the parser will accept from any response format.
KNOWN_ACTIONS = frozenset({
    "reference_search", "chunk_retrieval", "migration_analyzer", "finish",
})

#: Argument aliases seen across providers. Tool-tuned models emit the same
#: parameter under several spellings (``QUERY``/``query``/``q``), so the parser
#: normalises rather than requiring one exact key.
_ARG_ALIASES: dict[str, str] = {
    "query": "query", "q": "query", "search_query": "query",
    "version": "version", "sdk_version": "version", "api_version": "version",
    "chunk_id": "chunk_id", "chunkid": "chunk_id", "id": "chunk_id",
    "answer": "answer", "final_answer": "answer",
}


def _parse_tool_call(text: str) -> dict[str, Any] | None:
    """Read a native tool call, if this response is one.

    Models tuned for function calling answer a ReAct prompt with
    ``{"name": "reference_search", "arguments": {...}}`` instead of the line
    format. That is still a valid decision, so it is parsed rather than
    discarded. ``arguments`` may itself be a JSON string, or occasionally the
    ReAct line block, in which case this returns None and the caller falls
    through to the line parser.
    """
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    name = payload.get("name") or payload.get("tool") or payload.get("function")
    if not isinstance(name, str):
        return None
    action = name.strip().lower()
    if action not in KNOWN_ACTIONS:
        return None

    raw_args = payload.get("arguments", payload.get("parameters", {}))
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except (json.JSONDecodeError, ValueError):
            raw_args = {}
    if not isinstance(raw_args, dict):
        raw_args = {}

    params: dict[str, Any] = {"action": action}
    for key, value in raw_args.items():
        canonical = _ARG_ALIASES.get(str(key).strip().lower())
        if canonical and value not in (None, "", "null"):
            params[canonical] = value

    if action == "finish":
        params.setdefault("answer", text)
        params.setdefault("is_answerable", True)
    return params


def _parse_agent_action(llm_text: str) -> dict[str, Any]:
    """Parse the agent's action, in whichever format the model produced it.

    Order matters: a native tool call is checked first because its JSON body
    would otherwise be mangled by the line-format scanner below, which splits
    on the first ``:`` in every line.
    """
    native = _parse_tool_call(llm_text)
    if native is not None:
        return native

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

#: How many times a Week 8 mitigation may reject an action before giving up and
#: letting the agent through. Bounded so a mitigation can never itself loop.
MAX_GATE_REJECTIONS = 2
MAX_ARG_REJECTIONS = 2

GATE_CORRECTION = (
    "BLOCKED BY RETRIEVAL GATE: you tried to finish without any evidence from "
    "the corpus. An answer written from memory is not acceptable here. Call "
    "reference_search first and ground your answer in what it returns. If a "
    "search genuinely returns nothing relevant, then finish with the refusal."
)

#: Mitigations this loop knows how to apply. Exactly one may be active per run.
#:   "arg_schema_validation" — reject a reference_search whose `version` filter
#:       matches no sdk_version in the corpus, instead of letting it through to
#:       silently return zero results. Targets failure mode M3.
#:   "retrieval_gate" — refuse a `finish` taken with zero evidence collected.
#:       Targets failure mode M1.
SUPPORTED_MITIGATIONS = ("arg_schema_validation", "retrieval_gate")


def run_agent(
    question: str,
    config: BenchmarkConfig,
    collection_name: str = "sdk-v3-strategy-b",
    reasoner: OfflineReasoner | None = None,
    mitigation: str | None = None,
    evidence_filter: Callable[[str], str] | None = None,
) -> tuple[AgentState, CircuitBreaker, ExecutionTelemetry]:
    """
    Execute the ReAct agent loop.
    Returns (state, circuit_breaker, telemetry) for downstream evaluation.

    ``mitigation`` selects an optional Week 8 guard; ``"retrieval_gate"`` refuses
    a ``finish`` action taken with zero collected evidence and re-prompts. Both
    this and ``evidence_filter`` default to off, so Week 7 behaviour is unchanged.

    ``evidence_filter`` is applied to every chunk of retrieved text as it enters
    the agent's evidence store. The Week 8 prompt-injection experiment uses this
    single seam both to poison tool output (attack) and to sanitise it (defence).
    """
    cb = CircuitBreaker.from_config(config.safety)
    state = AgentState(question=question)
    telemetry = ExecutionTelemetry(
        architecture="agent",
        agent_steps=[],
        tools_selected=[],
        mitigation=mitigation,
    )
    offline = config.llm.mode == "offline"
    reasoner = reasoner or OfflineReasoner(max_steps=cb.max_iterations)

    last_observation = ""
    empty_search_count = 0
    step = 0
    gate_rejections = 0
    arg_rejections = 0

    def _filtered(text: str) -> str:
        return evidence_filter(text) if evidence_filter else text

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
                # A provider error is infrastructure, not a decision the agent
                # made. Mark it control so trajectory scoring does not read it
                # back as a hallucinated tool named "LLM call failed".
                trace_step = TraceStep(
                    step_number=step,
                    decision="LLM call failed",
                    observation=f"Error: {exc}",
                    action="terminate",
                    control=True,
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

            # ── Week 8 mitigation: argument schema validation ──
            # The `version` filter matches the corpus's sdk_version metadata, not
            # the API release date the question mentions. Left unchecked, a
            # plausible-looking version="2025-06-01" matches nothing and the tool
            # fails *silently* — the agent sees "0 chunks" and concludes the docs
            # do not cover the topic. Fail closed instead, and say why.
            if mitigation == "arg_schema_validation" and version:
                accepted = accepted_version_values(collection_name)
                if accepted and str(version) not in accepted and arg_rejections < MAX_ARG_REJECTIONS:
                    arg_rejections += 1
                    trace_step.tool = None
                    trace_step.control = True
                    trace_step.decision = (
                        f"Argument schema validation rejected reference_search "
                        f"({arg_rejections}/{MAX_ARG_REJECTIONS})"
                    )
                    trace_step.observation = (
                        f"REJECTED: VERSION={version!r} is not a valid filter value. "
                        f"The VERSION filter matches the corpus 'sdk_version' field, "
                        f"whose only accepted values are {sorted(accepted)} — it is "
                        f"not the API release date. Retry this search with one of "
                        f"those values, or omit VERSION entirely to search everything."
                    )
                    last_observation = trace_step.observation
                    telemetry.mitigation_interventions += 1
                    state.trace.append(trace_step)
                    telemetry.agent_steps.append(trace_step.to_dict())
                    continue

            search_input = ReferenceSearchInput(query=query, version=version)
            search_result = reference_search(search_input, collection_name=collection_name)

            state.search_queries_used.append(query)
            state.collected_evidence.extend([{
                "chunk_id": r.chunk_id,
                "text": _filtered(r.text),
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

            # An empty or malformed chunk_id is the agent choosing bad
            # arguments, not the harness failing. Letting pydantic's
            # ValidationError escape would kill the whole run and get it
            # recorded as an infrastructure error, hiding a real M3.
            try:
                retrieval_input = ChunkRetrievalInput(
                    chunk_id=chunk_id, collection_name=collection_name
                )
            except Exception as exc:
                trace_step.observation = f"Invalid chunk_retrieval arguments: {exc}"
                last_observation = trace_step.observation
                telemetry.tool_calls += 1
                telemetry.tools_selected.append("chunk_retrieval")
                state.trace.append(trace_step)
                telemetry.agent_steps.append(trace_step.to_dict())
                continue

            retrieval_result = chunk_retrieval(retrieval_input)

            if retrieval_result.chunk:
                state.collected_evidence.append({
                    "chunk_id": retrieval_result.chunk.chunk_id,
                    "text": _filtered(retrieval_result.chunk.text),
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
            # ── Week 8 mitigation: retrieval-gated finish ──
            # Refuse a final answer that is not grounded in a single retrieved
            # chunk. Targets failure mode M1 (skipped_retrieval) — the agent
            # reciting docs from pretrained memory instead of looking them up.
            if (
                mitigation == "retrieval_gate"
                and not state.collected_evidence
                and gate_rejections < MAX_GATE_REJECTIONS
            ):
                gate_rejections += 1
                trace_step.decision = (
                    f"Retrieval gate rejected finish "
                    f"({gate_rejections}/{MAX_GATE_REJECTIONS}): no evidence collected"
                )
                trace_step.tool = None
                trace_step.control = True
                trace_step.observation = GATE_CORRECTION
                last_observation = GATE_CORRECTION
                telemetry.mitigation_interventions += 1
                state.trace.append(trace_step)
                telemetry.agent_steps.append(trace_step.to_dict())
                continue

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