"""
eval/week10_failure_injection.py
--------------------------------
Week 10 failure experiment: force ``VersionDeprecationWorker`` to fail with an
HTTP 500-style server failure, then observe what the existing
``ManagerOrchestrator`` actually does.

Scope
-----
This module *only injects a fault*. It contains no retry policy, no fallback
strategy, no circuit breaker and no degraded-success path. Those are precisely
the things the experiment is trying to observe in the unmodified orchestrator,
so adding any of them here would destroy the measurement.

How the failure is injected
---------------------------
``VersionDeprecationWorker`` takes an optional per-instance ``tools`` mapping
(dependency injection). The mapping replaces one of the four upstream tool
calls with a callable that raises :class:`HttpServerError`. Nothing global is
patched: the default worker still calls the real ``reference_search``,
``chunk_retrieval``, ``migration_analyzer`` and ``accepted_version_values``.

The failure is raised at the ``reference_search`` seam because that is the
worker\'s first evidence-gathering call -- the point where a remote corpus
service would sit. The worker already wraps any exception from that call in
``VersionDeprecationWorkerError``; this experiment does not add that wrapping,
it only supplies the server-side cause.

Why a dedicated exception type
------------------------------
This repository has no HTTP layer: the retrieval stack is local (ChromaDB +
sentence-transformers) and no module models an HTTP status code. To keep the
failure honest -- a genuine server-side error rather than a fabricated
successful result or a vague ``RuntimeError`` -- :class:`HttpServerError`
carries the status code, the failing service and a retryability flag, so the
telemetry can record *what kind* of failure occurred instead of only that
"something went wrong".
"""

from __future__ import annotations

from typing import Any, Callable

from agent.multi_agent import ManagerOrchestrator, SquadRequest
from agent.workers.version_deprecation import VersionDeprecationWorker

#: The status code this experiment injects.
HTTP_500 = 500

#: Default upstream service named in the injected error.
DEFAULT_SERVICE = "reference_corpus_search"


class HttpServerError(RuntimeError):
    """An upstream service returned HTTP 500.

    Models a real server-side failure rather than an empty result. In
    particular it is *not* a successful response with zero results, which would
    be indistinguishable from "the corpus genuinely has nothing".
    """

    def __init__(
        self,
        service: str = DEFAULT_SERVICE,
        status_code: int = HTTP_500,
        detail: str = "upstream reference corpus service failed",
    ) -> None:
        self.service = service
        self.status_code = status_code
        self.detail = detail
        #: Server errors are transient by status class, but this experiment
        #: records the fact without acting on it.
        self.retryable = 500 <= status_code < 600
        super().__init__(
            f"HTTP {status_code} Internal Server Error from {service!r}: {detail}"
        )


def http_500_tool(
    service: str = DEFAULT_SERVICE,
    status_code: int = HTTP_500,
) -> Callable[..., Any]:
    """Build a drop-in replacement for a worker tool that always raises HTTP 500.

    Accepts ``*args, **kwargs`` so it can stand in for any of the worker's tool
    signatures without the caller having to match them.
    """

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise HttpServerError(service=service, status_code=status_code)

    return _raise


def failing_version_worker(
    collection_name: str | None = None,
    *,
    service: str = DEFAULT_SERVICE,
    tool_name: str = "reference_search",
) -> VersionDeprecationWorker:
    """A real ``VersionDeprecationWorker`` whose one injected tool raises HTTP 500.

    Every other tool call, and all of the worker\'s own bookkeeping (its handoff
    record, latency timing, token honesty and its error path), is the genuine
    production code.
    """
    return VersionDeprecationWorker(
        (lambda: collection_name) if collection_name else None,
        tools={tool_name: http_500_tool(service)},
    )


def build_http_500_multi_runner(
    target_questions: list[str] | str,
    *,
    service: str = DEFAULT_SERVICE,
    tool_name: str = "reference_search",
) -> Callable[..., Any]:
    """Return a ``multi_runner`` that fails exactly the given question(s).

    The returned callable matches the ``multi_runner`` signature accepted by
    :func:`eval.week10_race_runner.run_week10_race`. Every other question gets a
    completely normal orchestrator with the real tools, so the fault is scoped
    to exactly the selected evaluation case(s) and the rest of the race stays a
    clean control.
    """
    targets = (
        {target_questions} if isinstance(target_questions, str) else set(target_questions)
    )
    normalized = {q.strip() for q in targets}

    def multi_runner(question: str, config: Any, collection: str) -> Any:
        if question.strip() in normalized:
            version_worker = failing_version_worker(
                collection, service=service, tool_name=tool_name
            )
        else:
            version_worker = VersionDeprecationWorker(lambda: collection)
        orchestrator = ManagerOrchestrator(
            lambda: collection, version_worker=version_worker
        )
        return orchestrator.run(
            SquadRequest(
                question=question,
                config=config,
                collection_name=collection,
            )
        )

    return multi_runner