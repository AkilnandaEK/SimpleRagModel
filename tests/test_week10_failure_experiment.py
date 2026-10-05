"""
tests/test_week10_failure_experiment.py
-----------------------------------------
Focused characterization tests for the Week 10 failure experiment.

A real ``VersionDeprecationWorker`` has one upstream tool seam replaced with a
callable that raises HTTP 500. The failure is injected per-instance through
dependency injection; nothing global is patched and no production default path
changes.

These tests pin the behaviour that was *observed*. They deliberately assert no
retry, no fabricated evidence and no fabricated code. No retry or fallback logic
is added anywhere to make them pass -- that is the subject of the measurement,
not its remedy.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent.multi_agent import ManagerOrchestrator, SquadRequest
from agent.workers.version_deprecation import (
    VersionDeprecationRequest,
    VersionDeprecationWorker,
    VersionDeprecationWorkerError,
)
from benchmark.config import BenchmarkConfig
from eval.week10_failure_injection import (
    HTTP_500,
    HttpServerError,
    build_http_500_multi_runner,
    failing_version_worker,
    http_500_tool,
)
from eval.week10_race_runner import run_week10_race, select_week10_cases
from telemetry.week10_handoff import (
    CONTEXT_TOKEN_METHOD_CHARS_DIV_4,
    TOKEN_SOURCE_UNAVAILABLE,
)

COLLECTION = "sdk-v3-strategy-b"
QUESTION = "Compare how the context parameter format changed."


@pytest.fixture()
def config() -> BenchmarkConfig:
    return BenchmarkConfig()


def _run_failing_squad(config: BenchmarkConfig):
    """Real orchestrator, real workers; only the version search seam returns 500."""
    orchestrator = ManagerOrchestrator(
        lambda: COLLECTION,
        version_worker=failing_version_worker(COLLECTION),
    )
    return orchestrator.run(
        SquadRequest(
            question=QUESTION,
            config=config,
            collection_name=COLLECTION,
        )
    )


# ── The injected fault is a genuine server failure ─────────────────────────


def test_injected_error_is_an_http_500():
    err = HttpServerError()
    assert err.status_code == HTTP_500
    assert err.status_code == 500
    assert err.retryable is True
    assert "HTTP 500 Internal Server Error" in str(err)


def test_injected_tool_raises_rather_than_returning_empty_results():
    """A 500 must not be modelled as a valid empty response."""
    with pytest.raises(HttpServerError):
        http_500_tool()(ReferenceSearchInputStub(), collection_name=COLLECTION)


class ReferenceSearchInputStub:
    """Stand-in for the worker's tool input object."""


def test_worker_propagates_the_failure_instead_of_degrading_itself():
    """Degradation is the orchestrator's job; the worker stays honest."""
    worker = failing_version_worker(COLLECTION)
    with pytest.raises(VersionDeprecationWorkerError) as excinfo:
        worker.run(
            VersionDeprecationRequest(
                question=QUESTION,
                config=BenchmarkConfig(),
                collection_name=COLLECTION,
            )
        )
    assert "HTTP 500" in str(excinfo.value)


# ── Observed orchestrator behaviour ────────────────────────────────────────


def test_orchestrator_does_not_retry(config):
    """OBSERVED: the failing seam is invoked exactly once."""
    calls: list[int] = []

    def failing(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(1)
        raise HttpServerError()

    worker = VersionDeprecationWorker(
        lambda: COLLECTION, tools={"reference_search": failing}
    )
    response = ManagerOrchestrator(
        lambda: COLLECTION, version_worker=worker
    ).run(
        SquadRequest(
            question=QUESTION, config=config, collection_name=COLLECTION
        )
    )

    assert calls == [1]
    assert response.success is False


def test_orchestrator_degrades_instead_of_stopping(config):
    """OBSERVED: the run continues and the code worker is still delegated to."""
    response = _run_failing_squad(config)
    assert len(response.handoff_telemetry) == 2
    assert [t.destination_agent for t in response.handoff_telemetry] == [
        "version_deprecation_worker",
        "code_sample_worker",
    ]


def test_failed_worker_yields_no_evidence(config):
    response = _run_failing_squad(config)
    evidence = response.version_evidence
    assert evidence.supported is False
    assert evidence.has_evidence is False
    assert evidence.chunk_ids == []
    assert evidence.findings == []
    assert evidence.evidence_chunks == []


def test_squad_reports_failure_and_surfaces_the_error(config):
    response = _run_failing_squad(config)
    assert response.success is False
    assert len(response.errors) == 1
    assert "HTTP 500" in response.errors[0]


def test_no_code_is_fabricated_after_upstream_failure(config):
    response = _run_failing_squad(config)
    assert response.code_response is not None
    assert response.code_response.has_code is False
    assert response.code_response.supported is False
    assert "```" not in response.answer


def test_refusal_invents_no_case_specific_detail(config):
    """The answer must not leak the version strings the question supplied."""
    response = _run_failing_squad(config)
    lowered = response.answer.lower()
    assert "2022-11-28" not in lowered
    assert "2025-06-01" not in lowered
    assert "octocat" not in lowered


def test_refusal_names_the_upstream_failure(config):
    response = _run_failing_squad(config)
    assert "upstream" in response.answer.lower()
    assert "not generated" in response.answer.lower()


# ── Telemetry ──────────────────────────────────────────────────────────────


def test_version_handoff_telemetry_records_the_failure(config):
    response = _run_failing_squad(config)
    handoff = response.handoff_telemetry[0]

    assert handoff.source_agent == "manager_orchestrator"
    assert handoff.destination_agent == "version_deprecation_worker"
    assert handoff.task == "version_deprecation_analysis"
    assert handoff.success is False
    assert handoff.error is not None
    assert "HTTP 500" in handoff.error
    assert handoff.latency_ms >= 0.0
    assert handoff.handoff_context_tokens > 0
    assert handoff.context_token_method == CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    assert handoff.context_tokens_estimated is True


def test_failed_handoff_does_not_report_fake_token_usage(config):
    """Unmeasured provider usage stays None; it is never coerced to zero."""
    response = _run_failing_squad(config)
    handoff = response.handoff_telemetry[0]
    assert handoff.input_tokens is None
    assert handoff.output_tokens is None
    assert handoff.total_tokens is None
    assert handoff.token_source == TOKEN_SOURCE_UNAVAILABLE


def test_code_handoff_succeeds_by_refusing(config):
    """The downstream worker succeeds; it refuses rather than inventing code."""
    response = _run_failing_squad(config)
    handoff = response.handoff_telemetry[1]
    assert handoff.destination_agent == "code_sample_worker"
    assert handoff.task == "code_sample_generation"
    assert handoff.success is True
    assert handoff.error is None
    assert handoff.details["refused"] is True
    assert handoff.details["has_code"] is False


def test_only_the_question_crosses_the_boundary_after_failure(config):
    """No evidence text is forwarded, so context collapses to the question."""
    response = _run_failing_squad(config)
    expected = len(QUESTION) // 4
    assert {t.handoff_context_tokens for t in response.handoff_telemetry} == {
        expected
    }


def test_token_summary_reports_incomplete_measurement(config):
    summary = _run_failing_squad(config).token_summary
    assert summary.handoff_count == 2
    assert summary.unavailable_handoff_count == 2
    assert summary.measured_handoff_count == 0
    assert summary.tokens_complete is False


# ── Injection scope and default-path safety ────────────────────────────────


def test_injection_targets_exactly_one_question():
    """Other questions get a clean orchestrator built from the real tools."""
    runner = build_http_500_multi_runner(QUESTION)

    targeted = runner(QUESTION, BenchmarkConfig(), COLLECTION)
    assert targeted.success is False
    assert "HTTP 500" in targeted.errors[0]

    untouched = VersionDeprecationWorker(lambda: COLLECTION)
    assert "HTTP 500" not in str(untouched._reference_search)


def test_default_worker_still_uses_the_real_tool_implementations():
    """The DI seam must leave the production path byte-identical."""
    from tools.chunk_retrieval import chunk_retrieval
    from tools.corpus_facts import accepted_version_values
    from tools.migration_analyzer import migration_analyzer
    from tools.reference_search import reference_search

    worker = VersionDeprecationWorker(lambda: COLLECTION)
    assert worker._accepted_version_values is accepted_version_values
    assert worker._reference_search is reference_search
    assert worker._chunk_retrieval is chunk_retrieval
    assert worker._migration_analyzer is migration_analyzer


def test_failure_is_visible_through_the_shared_race_runner(config):
    entry = next(e for e in select_week10_cases(config, ["hard:01"]))

    def single_runner(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the single arm must not run in this test")

    result = run_week10_race(
        config,
        case_ids=["hard:01"],
        single_runner=single_runner,
        multi_runner=build_http_500_multi_runner(entry.question),
        verbose=False,
    )

    case = result.multi_agent_cases[0]
    assert case.case_id == "hard:01"
    assert case.failed_handoffs == 1
    assert case.successful_handoffs == 1
    assert any("HTTP 500" in message for message in case.handoff_errors)
    assert result.failure_injection_enabled is False


def test_race_runner_records_the_http_500_text_verbatim(config):
    entry = next(e for e in select_week10_cases(config, ["hard:01"]))

    def single_runner(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the single arm must not run in this test")

    result = run_week10_race(
        config,
        case_ids=["hard:01"],
        single_runner=single_runner,
        multi_runner=build_http_500_multi_runner(entry.question),
        verbose=False,
    )

    failed = [
        record
        for record in result.multi_agent_cases[0].handoff_telemetry
        if not record["success"]
    ]
    assert len(failed) == 1
    assert "HTTP 500" in failed[0]["error"]
    assert failed[0]["destination_agent"] == "version_deprecation_worker"
    assert failed[0]["task"] == "version_deprecation_analysis"


# ── Evaluator artifact this experiment exposed ─────────────────────────────


def test_shared_evaluator_marks_the_safe_refusal_correct(config):
    """CHARACTERIZATION ONLY -- this records an evaluator limitation.

    ``hard:01`` is a positive case with ``contains_exact_token=True``. The safe
    refusal text contains the word "version", which also appears in the golden
    answer, so the shared evaluator reports ``is_correct=True`` on roughly 6%
    genuine keyword overlap. The upstream HTTP 500 is invisible to the score.
    """
    from eval.evaluator import evaluate_answer
    from telemetry.telemetry import ExecutionTelemetry

    entry = next(e for e in select_week10_cases(config, ["hard:01"]))
    assert entry.is_negative_case is False
    assert entry.contains_exact_token is True

    refusal = (
        "Code sample not generated: upstream version/deprecation information "
        "is unavailable or unsupported."
    )
    evaluated = evaluate_answer(entry, refusal, ExecutionTelemetry())

    assert evaluated.is_correct is True
    assert evaluated.match_type == "contains_token"
    assert "'version'" in evaluated.details