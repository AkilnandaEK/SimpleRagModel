from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from benchmark.config import BenchmarkConfig
from telemetry.week10_handoff import (
    CONTEXT_TOKEN_METHOD_CHARS_DIV_4,
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_UNAVAILABLE,
    HandoffTelemetry,
    HandoffTokenSummary,
    aggregate_handoff_tokens,
    build_task_id,
    count_context_tokens,
    ContextTokenCounter,
    project_chars_div_4,
)
from agent.workers.version_deprecation import (
    VersionDeprecationEvidence,
    VersionDeprecationRequest,
    VersionDeprecationResponse,
    VersionDeprecationWorker,
    VersionDeprecationWorkerError,
    WorkerHandoff,
)
from agent.workers.code_sample import (
    CodeSampleRequest,
    CodeSampleResponse,
    CodeSampleWorker,
    CodeSampleWorkerError,
)

CollectionFactory = Callable[[], str]


@dataclass
class OrchestratorHandoff:
    source_agent: str
    destination_agent: str
    task: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SquadRequest:
    question: str
    config: BenchmarkConfig
    collection_name: str | None = None
    evidence_filter: Callable[[str], str] | None = None
    max_searches: int = 3
    max_retrievals: int = 2
    max_context_chunks: int = 2


@dataclass
class SquadResponse:
    answer: str
    success: bool
    version_evidence: VersionDeprecationEvidence
    code_response: CodeSampleResponse | None = None
    handoffs: list[OrchestratorHandoff] = field(default_factory=list)
    worker_handoffs: list[WorkerHandoff] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    # ── Week 10 handoff telemetry ──
    #: Joins to ExecutionTelemetry.run_id / trace_id for this same run.
    run_id: str = ''
    #: One observable record per Orchestrator -> Worker delegation.
    handoff_telemetry: list[HandoffTelemetry] = field(default_factory=list)
    #: Token rollup for the whole squad run (measured totals + completeness).
    token_summary: HandoffTokenSummary = field(default_factory=HandoffTokenSummary)

    def to_telemetry_dict(self) -> dict[str, Any]:
        return {
            'run_id': self.run_id,
            'answer': self.answer,
            'success': self.success,
            'latency_ms': round(self.latency_ms, 2),
            'errors': list(self.errors),
            'handoff_telemetry': [t.to_dict() for t in self.handoff_telemetry],
            'token_summary': self.token_summary.to_dict(),
        }


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


class ManagerOrchestrator:
    name = "manager_orchestrator"

    def __init__(
        self,
        collection_factory: CollectionFactory | None = None,
        version_worker: VersionDeprecationWorker | None = None,
        code_worker: CodeSampleWorker | None = None,
        context_counter: ContextTokenCounter = project_chars_div_4,
    ) -> None:
        self._collection_factory = collection_factory
        self._version_worker = version_worker or VersionDeprecationWorker(collection_factory)
        self._code_worker = code_worker or CodeSampleWorker(collection_factory)
        #: Correlation id for the in-flight run; set by run(), read by _to_telemetry().
        self._run_id = ''
        #: How agent-to-agent context re-send is counted. Defaults to the
        #: project's existing `len(text) // 4` convention so the Context
        #: Re-Send Multiplier stays comparable with Single Agent totals.
        self._context_counter = context_counter
        self._context_token_method = CONTEXT_TOKEN_METHOD_CHARS_DIV_4
        self._context_tokens_estimated = True

    def _get_collection(self, request: SquadRequest) -> str:
        if request.collection_name:
            return request.collection_name
        if self._collection_factory is not None:
            return self._collection_factory()
        return "sdk-v3-strategy-b"

    def run(self, request: SquadRequest) -> SquadResponse:
        start = _now_ms()
        run_id = uuid.uuid4().hex[:12]
        self._run_id = run_id
        collection = self._get_collection(request)
        errors: list[str] = []
        worker_handoffs: list[WorkerHandoff] = []
        handoffs: list[OrchestratorHandoff] = []
        telemetry_records: list[HandoffTelemetry] = []

        version_handoff = OrchestratorHandoff(
            source_agent=self.name,
            destination_agent=self._version_worker.name,
            task="version_deprecation_analysis",
        )
        code_handoff = OrchestratorHandoff(
            source_agent=self.name,
            destination_agent=self._code_worker.name,
            task="code_sample_generation",
        )

        version_response: VersionDeprecationResponse | None = None
        evidence: VersionDeprecationEvidence

        # Context actually crossing the Orchestrator -> Version Worker boundary.
        # Only real text is counted: the question. `config`, `evidence_filter`
        # and the integer knobs are internal objects/control values, not context.
        version_context_parts: list[str] = [request.question]

        version_start = _now_ms()
        try:
            version_response = self._version_worker.run(
                VersionDeprecationRequest(
                    question=request.question,
                    config=request.config,
                    collection_name=collection,
                    max_searches=request.max_searches,
                    max_retrievals=request.max_retrievals,
                    evidence_filter=request.evidence_filter,
                )
            )
            evidence = version_response.evidence
            worker_handoffs.append(version_response.handoff)
            version_handoff.success = True
            version_handoff.details = {
                "supported": evidence.supported,
                "has_evidence": evidence.has_evidence,
                "findings_count": len(evidence.findings),
                "evidence_count": len(evidence.evidence_chunks),
                "tool_calls": version_response.handoff.tool_calls,
                "llm_calls": 0,
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
            }
        except VersionDeprecationWorkerError as exc:
            # Explicit, observable failure boundary. No retry logic.
            message = str(exc)
            errors.append(message)
            evidence = VersionDeprecationEvidence(
                supported=False,
                has_evidence=False,
                reasoning=(
                    "Version/deprecation worker failed; downstream code sample "
                    "is refused rather than fabricated."
                ),
                warnings=[message],
            )
            version_handoff.success = False
            version_handoff.error = message
            version_handoff.details = {
                "supported": False,
                "has_evidence": False,
                "llm_calls": 0,
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
            }
        finally:
            version_handoff.latency_ms = _now_ms() - version_start
            if version_handoff.input_tokens is None or version_handoff.output_tokens is None:
                # Unmeasured, not zero: this delegation made no LLM call.
                version_handoff.input_tokens = None
                version_handoff.output_tokens = None
                version_handoff.total_tokens = None
            else:
                version_handoff.total_tokens = (
                    version_handoff.input_tokens + version_handoff.output_tokens
                )
            handoffs.append(version_handoff)
            telemetry_records.append(
                self._to_telemetry(
                    version_handoff,
                    len(telemetry_records),
                    request.question,
                    context_parts=version_context_parts,
                )
            )

        code_response: CodeSampleResponse | None = None
        # Context crossing the Orchestrator -> Code Worker boundary: the question
        # plus the evidence text forwarded from the Version Worker, bounded by the
        # same `max_context_chunks` the destination worker actually reads.
        code_context_parts: list[str] = [request.question]
        for chunk in evidence.evidence_chunks[: request.max_context_chunks]:
            code_context_parts.append(str(chunk.get('text', '')))

        code_start = _now_ms()
        try:
            code_response = self._code_worker.run(
                CodeSampleRequest(
                    question=request.question,
                    config=request.config,
                    version_evidence=evidence,
                    collection_name=collection,
                    max_context_chunks=request.max_context_chunks,
                    evidence_filter=request.evidence_filter,
                )
            )
            worker_handoffs.append(code_response.handoff)
            code_handoff.success = True
            code_handoff.details = {
                "supported": code_response.supported,
                "has_code": code_response.has_code,
                "warnings_count": len(code_response.warnings),
                "tool_calls": code_response.handoff.tool_calls,
                "llm_calls": 0,
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
                # Surface the worker's refusal state so a refusal caused by an
                # upstream failure stays visible in the handoff telemetry.
                "refused": code_response.handoff.details.get("refused", False),
            }
        except CodeSampleWorkerError as exc:
            message = str(exc)
            errors.append(message)
            code_handoff.success = False
            code_handoff.error = message
            code_handoff.details = {
                "supported": False,
                "has_code": False,
                "llm_calls": 0,
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
            }
        finally:
            code_handoff.latency_ms = _now_ms() - code_start
            if code_handoff.input_tokens is None or code_handoff.output_tokens is None:
                # Unmeasured, not zero: this delegation made no LLM call.
                code_handoff.input_tokens = None
                code_handoff.output_tokens = None
                code_handoff.total_tokens = None
            else:
                code_handoff.total_tokens = (
                    code_handoff.input_tokens + code_handoff.output_tokens
                )
            handoffs.append(code_handoff)
            telemetry_records.append(
                self._to_telemetry(
                    code_handoff,
                    len(telemetry_records),
                    request.question,
                    context_parts=code_context_parts,
                )
            )

        if code_response is None or not code_response.has_code:
            answer = (
                code_response.explanation
                if code_response is not None
                else "Code sample worker failed; no answer produced."
            )
        else:
            answer = code_response.code

        success = version_handoff.success and code_handoff.success and bool(answer)

        return SquadResponse(
            answer=answer,
            success=success,
            version_evidence=evidence,
            code_response=code_response,
            handoffs=handoffs,
            worker_handoffs=worker_handoffs,
            errors=errors,
            latency_ms=_now_ms() - start,
            run_id=run_id,
            handoff_telemetry=telemetry_records,
            token_summary=aggregate_handoff_tokens(telemetry_records),
        )

    def _to_telemetry(
        self,
        handoff: OrchestratorHandoff,
        sequence: int,
        question: str,
        context_parts: list[str] | None = None,
    ) -> HandoffTelemetry:
        '''Project one delegation into its Week 10 handoff telemetry record.

        The Orchestrator's view is authoritative here because it is the party
        that delegates, and it survives worker exceptions (the worker's own
        handoff is unwound when it raises). Token fields pass through as-is:
        ``None`` means unmeasured provider usage, never zero.
        '''
        if handoff.input_tokens is None or handoff.output_tokens is None:
            token_source = TOKEN_SOURCE_UNAVAILABLE
            input_tokens: int | None = None
            output_tokens: int | None = None
        else:
            token_source = TOKEN_SOURCE_MEASURED
            input_tokens = handoff.input_tokens
            output_tokens = handoff.output_tokens

        return HandoffTelemetry(
            run_id=self._run_id,
            sequence=sequence,
            source_agent=handoff.source_agent,
            destination_agent=handoff.destination_agent,
            task=handoff.task,
            task_id=build_task_id(self._run_id, sequence, handoff.task),
            question=question,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=handoff.latency_ms,
            success=handoff.success,
            error=handoff.error,
            token_source=token_source,
            handoff_context_tokens=count_context_tokens(
                context_parts or [], self._context_counter
            ),
            context_token_method=self._context_token_method,
            context_tokens_estimated=self._context_tokens_estimated,
            llm_calls=int(handoff.details.get('llm_calls', 0)),
            tool_calls=int(handoff.details.get('tool_calls', 0)),
            details=dict(handoff.details),
        )