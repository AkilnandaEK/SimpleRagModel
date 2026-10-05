from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from benchmark.config import BenchmarkConfig
from agent.workers.version_deprecation import VersionDeprecationEvidence, WorkerHandoff
from telemetry.week10_handoff import TOKEN_SOURCE_UNAVAILABLE

CollectionFactory = Callable[[], str]

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)


@dataclass
class CodeSampleRequest:
    question: str
    config: BenchmarkConfig
    version_evidence: VersionDeprecationEvidence
    collection_name: str | None = None
    include_context: bool = True
    max_context_chunks: int = 2
    max_code_blocks: int = 2
    evidence_filter: Callable[[str], str] | None = None


@dataclass
class CodeSampleResponse:
    code: str
    explanation: str
    supported: bool
    has_code: bool
    warnings: list[str] = field(default_factory=list)
    evidence_used: list[dict[str, Any]] = field(default_factory=list)
    handoff: WorkerHandoff = field(
        default_factory=lambda: WorkerHandoff(
            source_agent="orchestrator",
            destination_agent="code_sample_worker",
            task="code_sample_generation",
        )
    )


class CodeSampleWorkerError(RuntimeError):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _extract_code_blocks(text: str) -> list[str]:
    return [match.strip() for match in _CODE_FENCE.findall(text or "") if match.strip()]


class CodeSampleWorker:
    name = "code_sample_worker"

    def __init__(self, collection_factory: CollectionFactory | None = None) -> None:
        self._collection_factory = collection_factory

    def _get_collection(self, request: CodeSampleRequest) -> str:
        if request.collection_name:
            return request.collection_name
        if self._collection_factory is not None:
            return self._collection_factory()
        return "sdk-v3-strategy-b"

    def _refuse(self, reason: str) -> CodeSampleResponse:
        return CodeSampleResponse(
            code="",
            explanation=(
                "Code sample not generated: "
                f"{reason}. No SDK or version details are invented when upstream "
                "version/deprecation information is unavailable or unsupported."
            ),
            supported=False,
            has_code=False,
            warnings=[
                "Upstream version/deprecation evidence is unsupported; "
                "refusing to fabricate version-dependent code."
            ],
        )

    def run(self, request: CodeSampleRequest) -> CodeSampleResponse:
        start = _now_ms()
        handoff = WorkerHandoff(
            source_agent="orchestrator",
            destination_agent=self.name,
            task="code_sample_generation",
            success=True,
        )
        try:
            evidence = request.version_evidence
            collection = self._get_collection(request)

            if not evidence.supported:
                handoff.details = {
                    "collection": collection,
                    "refused": True,
                    "upstream_supported": evidence.supported,
                    "upstream_has_evidence": evidence.has_evidence,
                    "token_source": TOKEN_SOURCE_UNAVAILABLE,
                    "llm_calls": 0,
                    "tool_calls": 0,
                }
                response = self._refuse(
                    "upstream version/deprecation information is unavailable or unsupported"
                )
                response.handoff = handoff
                return response

            if not evidence.has_evidence or not evidence.evidence_chunks:
                handoff.details = {
                    "collection": collection,
                    "refused": True,
                    "upstream_supported": evidence.supported,
                    "upstream_has_evidence": evidence.has_evidence,
                    "token_source": TOKEN_SOURCE_UNAVAILABLE,
                    "llm_calls": 0,
                    "tool_calls": 0,
                }
                response = self._refuse("upstream evidence contained no chunks to ground a sample")
                response.handoff = handoff
                return response

            evidence_used = list(evidence.evidence_chunks)[: request.max_context_chunks]
            code_blocks: list[str] = []
            for chunk in evidence_used:
                text = request.evidence_filter(chunk.get("text", "")) if request.evidence_filter else chunk.get("text", "")
                code_blocks.extend(_extract_code_blocks(text))

            code = "\n\n".join(code_blocks[: request.max_code_blocks]).strip()
            has_code = bool(code)

            if has_code:
                explanation = (
                    "Code sample extracted verbatim from verified corpus evidence; "
                    "no SDK or version details were invented."
                )
            else:
                explanation = (
                    "Upstream evidence is supported but contains no concrete code block "
                    "to extract, so no code sample is emitted."
                )

            warnings: list[str] = []
            if not has_code:
                warnings.append(
                    "No concrete code block found in verified evidence; code sample omitted."
                )

            handoff.details = {
                "collection": collection,
                "refused": False,
                "evidence_used": len(evidence_used),
                "code_blocks_found": len(code_blocks),
                "has_code": has_code,
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
                "llm_calls": 0,
                "tool_calls": 0,
            }
            return CodeSampleResponse(
                code=code,
                explanation=explanation,
                supported=True,
                has_code=has_code,
                warnings=warnings,
                evidence_used=evidence_used,
                handoff=handoff,
            )
        except CodeSampleWorkerError:
            handoff.success = False
            handoff.error = "CodeSampleWorkerError"
            handoff.details = {
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
                "llm_calls": 0,
                "tool_calls": 0,
            }
            raise
        except Exception as exc:
            handoff.success = False
            handoff.error = str(exc)
            handoff.details = {
                "token_source": TOKEN_SOURCE_UNAVAILABLE,
                "llm_calls": 0,
                "tool_calls": 0,
            }
            raise CodeSampleWorkerError(
                f"CodeSampleWorker unexpected error: {exc}", cause=exc
            ) from exc
        finally:
            handoff.latency_ms = _now_ms() - start
            # No LLM call happens here, so token usage is unavailable rather
            # than zero. Zero would claim a measured cost of nothing.
            if handoff.input_tokens is not None and handoff.output_tokens is not None:
                handoff.total_tokens = handoff.input_tokens + handoff.output_tokens
            else:
                handoff.input_tokens = None
                handoff.output_tokens = None
                handoff.total_tokens = None