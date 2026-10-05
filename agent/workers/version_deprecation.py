from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from benchmark.config import BenchmarkConfig
from telemetry.week10_handoff import (
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_UNAVAILABLE,
    HandoffTelemetry,
    build_task_id,
)
from tools.chunk_retrieval import ChunkRetrievalInput, chunk_retrieval
from tools.corpus_facts import accepted_version_values
from tools.migration_analyzer import MigrationAnalyzerInput, migration_analyzer
from tools.reference_search import ReferenceSearchInput, reference_search

CollectionFactory = Callable[[], str]
ToolImpl = Callable[..., Any]

@dataclass
class WorkerHandoff:
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
    #: Real tool invocations made during this handoff. Counted, not estimated.
    tool_calls: int = 0

    def to_telemetry(
        self,
        *,
        run_id: str = '',
        sequence: int = 0,
        question: str = '',
        tool_calls: int = 0,
    ) -> HandoffTelemetry:
        '''Project this handoff into the Week 10 handoff telemetry record.

        Token counts are carried through verbatim. When the worker ran without
        an LLM call they stay ``None`` (``token_source='unavailable'``) instead
        of being coerced to zero.
        '''
        if self.input_tokens is None or self.output_tokens is None:
            token_source = TOKEN_SOURCE_UNAVAILABLE
            input_tokens: int | None = None
            output_tokens: int | None = None
        else:
            token_source = TOKEN_SOURCE_MEASURED
            input_tokens = self.input_tokens
            output_tokens = self.output_tokens

        return HandoffTelemetry(
            run_id=run_id,
            sequence=sequence,
            source_agent=self.source_agent,
            destination_agent=self.destination_agent,
            task=self.task,
            task_id=build_task_id(run_id, sequence, self.task),
            question=question,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=self.latency_ms,
            success=self.success,
            error=self.error,
            token_source=token_source,
            tool_calls=tool_calls or self.tool_calls,
            details=dict(self.details),
        )

@dataclass
class VersionDeprecationEvidence:
    supported: bool
    has_evidence: bool
    version: str | None = None
    deprecated: bool = False
    findings: list[str] = field(default_factory=list)
    evidence_chunks: list[dict[str, Any]] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    reasoning: str = ''
    warnings: list[str] = field(default_factory=list)

@dataclass
class VersionDeprecationRequest:
    question: str
    config: BenchmarkConfig
    collection_name: str | None = None
    max_searches: int = 3
    max_retrievals: int = 2
    evidence_filter: Callable[[str], str] | None = None

@dataclass
class VersionDeprecationResponse:
    evidence: VersionDeprecationEvidence
    handoff: WorkerHandoff
    accepted_versions: frozenset[str] = field(default_factory=frozenset)
    accepted_versions_list: list[str] = field(default_factory=list)

class VersionDeprecationWorkerError(RuntimeError):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause

def _now_ms() -> float:
    return time.perf_counter() * 1000.0

def _filtered(text: str, filter_fn: Callable[[str], str] | None) -> str:
    return filter_fn(text) if filter_fn else text

class VersionDeprecationWorker:
    name = 'version_deprecation_worker'

    def __init__(
        self,
        collection_factory: CollectionFactory | None = None,
        tools: dict[str, ToolImpl] | None = None,
    ) -> None:
        self._collection_factory = collection_factory
        # Dependency-injection seam for the four upstream tool calls. Defaults
        # are the real implementations, so omitting `tools` leaves production
        # behaviour byte-identical. Only an explicit caller (e.g. the Week 10
        # failure experiment) can substitute a tool, and substitution is
        # per-instance -- nothing global is patched.
        injected = tools or {}
        self._accepted_version_values = injected.get(
            'accepted_version_values', accepted_version_values
        )
        self._reference_search = injected.get('reference_search', reference_search)
        self._chunk_retrieval = injected.get('chunk_retrieval', chunk_retrieval)
        self._migration_analyzer = injected.get('migration_analyzer', migration_analyzer)

    def _get_collection(self, request: VersionDeprecationRequest) -> str:
        if request.collection_name:
            return request.collection_name
        if self._collection_factory is not None:
            return self._collection_factory()
        return 'sdk-v3-strategy-b'

    def run(self, request: VersionDeprecationRequest) -> VersionDeprecationResponse:
        start = _now_ms()
        collection = self._get_collection(request)
        handoff = WorkerHandoff(
            source_agent='orchestrator',
            destination_agent=self.name,
            task='version_deprecation_analysis',
            success=True,
        )
        evidence = VersionDeprecationEvidence(supported=False, has_evidence=False)
        # Real counters only. This worker performs no LLM call, so token fields
        # stay None (token_source='unavailable') rather than being zero-filled.
        tool_calls = 0

        try:
            accepted = self._accepted_version_values(collection)
            tool_calls += 1
            accepted_list = sorted(str(v) for v in accepted)

            search_results: list[dict[str, Any]] = []
            seen_queries: set[str] = set()
            queries = [
                request.question,
                f'{request.question} version',
                f'{request.question} deprecated deprecation api version',
            ]
            for q in queries[: request.max_searches]:
                if not q or q in seen_queries:
                    continue
                seen_queries.add(q)
                try:
                    sr = self._reference_search(
                        ReferenceSearchInput(query=q, version=None),
                        collection_name=collection,
                    )
                    tool_calls += 1
                except Exception as exc:
                    raise VersionDeprecationWorkerError(f'reference_search failed for query {q!r}: {exc}', cause=exc) from exc
                for r in sr.results:
                    search_results.append({
                        'chunk_id': r.chunk_id,
                        'text': _filtered(r.text, request.evidence_filter),
                        'source_file': r.source_file,
                        'metadata': r.metadata,
                    })
                if len(search_results) >= request.max_retrievals:
                    break

            retrieved: list[dict[str, Any]] = []
            for sres in search_results[: request.max_retrievals]:
                cid = sres.get('chunk_id')
                if not cid:
                    continue
                try:
                    rr = self._chunk_retrieval(ChunkRetrievalInput(chunk_id=str(cid), collection_name=collection))
                    tool_calls += 1
                except Exception as exc:
                    raise VersionDeprecationWorkerError(f'chunk_retrieval failed for chunk_id={cid}: {exc}', cause=exc) from exc
                if rr.chunk:
                    retrieved.append({
                        'chunk_id': rr.chunk.chunk_id,
                        'text': _filtered(rr.chunk.text, request.evidence_filter),
                        'source_file': rr.chunk.source_file,
                        'metadata': rr.chunk.metadata,
                    })

            merged: dict[str, dict[str, Any]] = {}
            for item in search_results + retrieved:
                cid = item.get('chunk_id')
                if not cid:
                    continue
                if cid not in merged:
                    merged[cid] = item
            evidence_chunks = list(merged.values())

            analysis_text = ''
            is_answerable = False
            if evidence_chunks:
                try:
                    ar = self._migration_analyzer(MigrationAnalyzerInput(
                        question=request.question,
                        evidence_chunks=[{'chunk_id': e.get('chunk_id',''), 'text': e.get('text','')} for e in evidence_chunks],
                    ))
                    tool_calls += 1
                    analysis_text = ar.evidence or ''
                    is_answerable = ar.is_answerable
                except Exception as exc:
                    raise VersionDeprecationWorkerError(f'migration_analyzer failed: {exc}', cause=exc) from exc

            findings: list[str] = []
            for line in analysis_text.splitlines():
                sline = line.strip()
                if sline and len(sline) > 10:
                    findings.append(sline)

            chunk_ids = [str(e.get('chunk_id')) for e in evidence_chunks if e.get('chunk_id')]
            source_files = sorted({str(e.get('source_file')) for e in evidence_chunks if e.get('source_file')})

            has_evidence = len(evidence_chunks) > 0
            supported = has_evidence and (is_answerable or len(findings) > 0)

            reasoning = (
                'Evidence-backed analysis from reference corpus.'
                if supported
                else ('No sufficient evidence in corpus to support a concrete version/deprecation claim.'
                      if not has_evidence else 'Evidence present but not sufficient to make a confident claim.')
            )

            evidence = VersionDeprecationEvidence(
                supported=supported,
                has_evidence=has_evidence,
                findings=findings,
                evidence_chunks=evidence_chunks,
                source_files=source_files,
                chunk_ids=chunk_ids,
                reasoning=reasoning,
            )
            handoff.success = True
            handoff.tool_calls = tool_calls
            handoff.details = {
                'collection': collection,
                'search_results_count': len(search_results),
                'retrieved_count': len(retrieved),
                'evidence_count': len(evidence_chunks),
                'is_answerable': is_answerable,
                'findings_count': len(findings),
                'accepted_versions': accepted_list,
                'token_source': TOKEN_SOURCE_UNAVAILABLE,
                'llm_calls': 0,
                'tool_calls': tool_calls,
            }
        except VersionDeprecationWorkerError as exc:
            handoff.success = False
            handoff.error = str(exc)
            handoff.tool_calls = tool_calls
            handoff.details = {
                'token_source': TOKEN_SOURCE_UNAVAILABLE,
                'llm_calls': 0,
                'tool_calls': tool_calls,
            }
            evidence = VersionDeprecationEvidence(supported=False, has_evidence=False, reasoning=f'Worker failure: {exc}')
            raise
        except Exception as exc:
            handoff.success = False
            handoff.error = str(exc)
            handoff.tool_calls = tool_calls
            handoff.details = {
                'token_source': TOKEN_SOURCE_UNAVAILABLE,
                'llm_calls': 0,
                'tool_calls': tool_calls,
            }
            evidence = VersionDeprecationEvidence(supported=False, has_evidence=False, reasoning=f'Worker unexpected failure: {exc}')
            raise VersionDeprecationWorkerError(f'VersionDeprecationWorker unexpected error: {exc}', cause=exc) from exc
        finally:
            handoff.latency_ms = _now_ms() - start
            # Only a measured LLM call may populate tokens. No LLM call happens
            # here, so both stay None (unavailable) instead of becoming 0.
            if handoff.input_tokens is not None and handoff.output_tokens is not None:
                handoff.total_tokens = handoff.input_tokens + handoff.output_tokens
            else:
                handoff.input_tokens = None
                handoff.output_tokens = None
                handoff.total_tokens = None

        return VersionDeprecationResponse(
            evidence=evidence,
            handoff=handoff,
            accepted_versions=accepted,
            accepted_versions_list=accepted_list,
        )
