from __future__ import annotations

import statistics
from typing import Any

import pytest

from benchmark.config import BenchmarkConfig
from agent.multi_agent import ManagerOrchestrator, SquadRequest
from eval import week10_race_runner as wrr
from eval.week10_race_runner import (
    ARM_MULTI,
    ARM_SINGLE,
    WEEK10_CASE_IDS,
    CaseResult,
    run_week10_race,
    select_week10_cases,
)
from telemetry.week10_handoff import (
    CONTEXT_TOKEN_METHOD_CHARS_DIV_4,
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_UNAVAILABLE,
    HandoffTelemetry,
    aggregate_handoff_tokens,
    count_context_tokens,
    project_chars_div_4,
)
from agent.workers import version_deprecation as vd
from agent.workers.code_sample import CodeSampleRequest, CodeSampleWorker
from agent.workers.version_deprecation import (
    VersionDeprecationEvidence,
    VersionDeprecationRequest,
    VersionDeprecationResponse,
    VersionDeprecationWorker,
    VersionDeprecationWorkerError,
    WorkerHandoff,
)

COLLECTION = "sdk-v3-strategy-b"

EVIDENCE_TEXT = (
    "Strategy `v3` replaces the legacy `create_order` helper.\n"
    "```python\n"
    "from strategy import Strategy\n\n"
    "s = Strategy(version=\"v3\")\n"
    "s.create_order(symbol=\"BTC-USD\")\n"
    "```\n"
    "`create_order` is deprecated as of the v2 to v3 migration.\n"
)


def _search_output(query: str, chunk_id: str, text: str) -> Any:
    from tools.reference_search import ReferenceSearchOutput, SearchResult

    return ReferenceSearchOutput(
        query=query,
        results=[
            SearchResult(
                chunk_id=chunk_id,
                text=text,
                distance=0.1,
                source_file="docs/migration.md",
                relevance=0.9,
                metadata={"section": "v3"},
            )
        ],
        result_count=1,
        collection_searched=COLLECTION,
        status="found",
    )


def _retrieval_output(chunk_id: str, text: str) -> Any:
    from tools.chunk_retrieval import ChunkContent, ChunkRetrievalOutput

    return ChunkRetrievalOutput(
        requested_chunk_id=chunk_id,
        chunk=ChunkContent(
            chunk_id=chunk_id,
            text=text,
            source_file="docs/migration.md",
            page_id="p1",
            section="v3",
            metadata={"section": "v3"},
        ),
        context_chunks=[],
        status="found",
    )


def _analysis_output(is_answerable: bool, evidence: str) -> Any:
    from tools.migration_analyzer import MigrationAnalysisOutput

    return MigrationAnalysisOutput(
        is_answerable=is_answerable,
        migration_changes=[],
        evidence=evidence,
        source_references=["docs/migration.md"],
        confidence=0.9 if is_answerable else 0.1,
        refusal_reason=None if is_answerable else "insufficient evidence",
    )


def _patch_tools(
    monkeypatch: pytest.MonkeyPatch,
    *,
    answerable: bool = True,
    chunk_id: str = "chunk-1",
    text: str = EVIDENCE_TEXT,
    search_raises: Exception | None = None,
) -> None:
    monkeypatch.setattr(
        vd, "accepted_version_values", lambda collection: frozenset({"v2", "v3"})
    )

    def _search(input_data: Any, collection_name: str = COLLECTION) -> Any:
        if search_raises is not None:
            raise search_raises
        return _search_output(input_data.query, chunk_id, text)

    monkeypatch.setattr(vd, "reference_search", _search)
    monkeypatch.setattr(
        vd, "chunk_retrieval", lambda input_data: _retrieval_output(chunk_id, text)
    )
    monkeypatch.setattr(
        vd,
        "migration_analyzer",
        lambda input_data: _analysis_output(answerable, "v3 is supported; v2 deprecated."),
    )


# --------------------------------------------------------------------------
# Version / Deprecation Worker
# --------------------------------------------------------------------------


def test_version_worker_returns_evidence_backed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tools(monkeypatch)
    worker = VersionDeprecationWorker(lambda: COLLECTION)

    response = worker.run(
        VersionDeprecationRequest(
            question="How do I create an order in v3?", config=BenchmarkConfig()
        )
    )

    assert isinstance(response, VersionDeprecationResponse)
    assert response.evidence.supported is True
    assert response.evidence.has_evidence is True
    assert response.evidence.source_files == ["docs/migration.md"]
    assert response.evidence.chunk_ids == ["chunk-1"]
    assert response.evidence.findings
    assert sorted(response.accepted_versions_list) == ["v2", "v3"]
    assert response.handoff.success is True
    assert response.handoff.destination_agent == "version_deprecation_worker"


def test_version_worker_reports_unsupported_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch, answerable=False, chunk_id="", text="")

    def _empty_search(input_data: Any, collection_name: str = COLLECTION) -> Any:
        from tools.reference_search import ReferenceSearchOutput

        return ReferenceSearchOutput(
            query=input_data.query,
            results=[],
            result_count=0,
            collection_searched=collection_name,
            status="not_found",
        )

    monkeypatch.setattr(vd, "reference_search", _empty_search)
    worker = VersionDeprecationWorker(lambda: COLLECTION)

    response = worker.run(
        VersionDeprecationRequest(question="Unknown API?", config=BenchmarkConfig())
    )

    assert response.evidence.has_evidence is False
    assert response.evidence.supported is False
    assert response.handoff.success is True


def test_version_worker_raises_explicit_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch, search_raises=RuntimeError("http 500"))

    calls = {"n": 0}
    original = vd.reference_search

    def _counting_search(input_data: Any, collection_name: str = COLLECTION) -> Any:
        calls["n"] += 1
        return original(input_data, collection_name=collection_name)

    monkeypatch.setattr(vd, "reference_search", _counting_search)
    worker = VersionDeprecationWorker(lambda: COLLECTION)

    with pytest.raises(VersionDeprecationWorkerError) as excinfo:
        worker.run(
            VersionDeprecationRequest(question="boom?", config=BenchmarkConfig())
        )

    assert "reference_search failed" in str(excinfo.value)
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# Code-Sample Worker
# --------------------------------------------------------------------------


def test_code_worker_extracts_code_from_verified_evidence() -> None:
    worker = CodeSampleWorker(lambda: COLLECTION)
    evidence = VersionDeprecationEvidence(
        supported=True,
        has_evidence=True,
        findings=["v3 is supported; v2 deprecated."],
        evidence_chunks=[
            {"chunk_id": "chunk-1", "text": EVIDENCE_TEXT, "source_file": "docs/migration.md"}
        ],
    )

    response = worker.run(
        CodeSampleRequest(
            question="How do I create an order in v3?",
            config=BenchmarkConfig(),
            version_evidence=evidence,
        )
    )

    assert response.supported is True
    assert response.has_code is True
    assert 'Strategy(version="v3")' in response.code
    assert response.evidence_used and response.evidence_used[0]["chunk_id"] == "chunk-1"
    assert response.handoff.success is True


def test_code_worker_refuses_when_upstream_unsupported() -> None:
    worker = CodeSampleWorker(lambda: COLLECTION)
    evidence = VersionDeprecationEvidence(
        supported=False, has_evidence=False, reasoning="no evidence"
    )

    response = worker.run(
        CodeSampleRequest(
            question="How do I create an order in v3?",
            config=BenchmarkConfig(),
            version_evidence=evidence,
        )
    )

    assert response.supported is False
    assert response.has_code is False
    assert response.code == ""
    assert response.warnings
    assert "no fabrication" in response.explanation.lower() or "not generated" in response.explanation.lower()
    assert response.handoff.details["refused"] is True


# --------------------------------------------------------------------------
# Manager Orchestrator
# --------------------------------------------------------------------------


def test_orchestrator_runs_full_squad_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    assert response.success is True
    assert response.errors == []
    assert response.version_evidence.supported is True
    assert response.code_response is not None
    assert response.code_response.has_code is True
    assert 'Strategy(version="v3")' in response.answer

    tasks = [h.task for h in response.handoffs]
    assert tasks == ["version_deprecation_analysis", "code_sample_generation"]
    assert all(h.success for h in response.handoffs)
    assert len(response.worker_handoffs) == 2
    assert all(isinstance(h, WorkerHandoff) for h in response.worker_handoffs)
    assert response.latency_ms > 0.0


def test_orchestrator_records_typed_handoff_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    for handoff in [*response.handoffs, *response.worker_handoffs]:
        assert handoff.source_agent
        assert handoff.destination_agent
        assert handoff.task
        # Tokens are unmeasured (no LLM call), so they stay None rather than 0.
        assert handoff.input_tokens is None
        assert handoff.output_tokens is None
        assert handoff.total_tokens is None
        assert handoff.latency_ms >= 0.0
        assert isinstance(handoff.success, bool)
        assert handoff.error is None or isinstance(handoff.error, str)


def test_orchestrator_degrades_gracefully_when_version_worker_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch, search_raises=RuntimeError("http 500"))
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    assert response.success is False
    assert response.errors
    assert "reference_search failed" in response.errors[0]
    assert response.version_evidence.supported is False

    version_handoff = response.handoffs[0]
    assert version_handoff.success is False
    assert version_handoff.error is not None

    assert response.code_response is not None
    assert response.code_response.has_code is False
    assert response.code_response.code == ""
    assert response.answer


# ==========================================================================
# Week 10 handoff telemetry
# ==========================================================================


def _telemetry_by_task(response: Any, task: str) -> HandoffTelemetry:
    matches = [t for t in response.handoff_telemetry if t.task == task]
    assert len(matches) == 1, f"expected exactly one telemetry record for {task}"
    return matches[0]


def test_successful_version_handoff_records_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    record = _telemetry_by_task(response, "version_deprecation_analysis")
    assert record.source_agent == "manager_orchestrator"
    assert record.destination_agent == "version_deprecation_worker"
    assert record.success is True
    assert record.error is None
    assert record.run_id == response.run_id
    assert record.sequence == 0
    assert record.task_id == f"{response.run_id}:0:version_deprecation_analysis"
    assert record.question == "How do I create an order in v3?"
    assert record.latency_ms > 0.0
    assert record.tool_calls > 0
    assert record.details["supported"] is True


def test_successful_code_sample_handoff_records_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    record = _telemetry_by_task(response, "code_sample_generation")
    assert record.source_agent == "manager_orchestrator"
    assert record.destination_agent == "code_sample_worker"
    assert record.success is True
    assert record.error is None
    assert record.sequence == 1
    assert record.task_id == f"{response.run_id}:1:code_sample_generation"
    assert record.latency_ms > 0.0
    assert record.details["has_code"] is True


def test_both_delegations_are_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    assert len(response.handoff_telemetry) == 2
    destinations = [t.destination_agent for t in response.handoff_telemetry]
    assert destinations == ["version_deprecation_worker", "code_sample_worker"]
    assert all(t.source_agent == "manager_orchestrator" for t in response.handoff_telemetry)


def test_failed_version_handoff_records_success_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch, search_raises=RuntimeError("http 500"))
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    record = _telemetry_by_task(response, "version_deprecation_analysis")
    assert record.success is False
    # The failure boundary stays observable rather than being swallowed.
    assert response.success is False
    assert response.errors


def test_failed_handoff_records_error_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch, search_raises=RuntimeError("http 500"))
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    record = _telemetry_by_task(response, "version_deprecation_analysis")
    assert record.error is not None
    assert "reference_search failed" in record.error
    assert record.latency_ms > 0.0

    # The downstream code handoff still runs and is still observable.
    code_record = _telemetry_by_task(response, "code_sample_generation")
    assert code_record.success is True
    assert code_record.details["refused"] is True


def test_token_usage_is_unavailable_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    for record in response.handoff_telemetry:
        # No LLM call happened, so there is no provider token usage to report.
        assert record.token_source == TOKEN_SOURCE_UNAVAILABLE
        assert record.tokens_available is False
        assert record.input_tokens is None
        assert record.output_tokens is None
        assert record.total_tokens is None
        assert record.llm_calls == 0

    summary = response.token_summary
    assert summary.handoff_count == 2
    assert summary.measured_handoff_count == 0
    assert summary.unavailable_handoff_count == 2
    assert summary.measured_total_tokens == 0
    # Incomplete numerator must be flagged, not silently treated as a real 0.
    assert summary.tokens_complete is False


def test_measured_token_values_are_preserved_verbatim() -> None:
    record = HandoffTelemetry(
        run_id="run123",
        sequence=0,
        source_agent="manager_orchestrator",
        destination_agent="version_deprecation_worker",
        task="version_deprecation_analysis",
        input_tokens=1200,
        output_tokens=340,
        token_source=TOKEN_SOURCE_MEASURED,
        llm_calls=1,
    )

    assert record.total_tokens == 1540
    assert record.tokens_available is True

    summary = aggregate_handoff_tokens([record])
    assert summary.measured_input_tokens == 1200
    assert summary.measured_output_tokens == 340
    assert summary.measured_total_tokens == 1540
    assert summary.measured_handoff_count == 1
    assert summary.unavailable_handoff_count == 0
    assert summary.tokens_complete is True


def test_mixed_handoffs_aggregate_only_real_measurements() -> None:
    measured = HandoffTelemetry(
        run_id="run123",
        sequence=0,
        task="version_deprecation_analysis",
        input_tokens=100,
        output_tokens=50,
        token_source=TOKEN_SOURCE_MEASURED,
        llm_calls=1,
    )
    unmeasured = HandoffTelemetry(
        run_id="run123",
        sequence=1,
        task="code_sample_generation",
        token_source=TOKEN_SOURCE_UNAVAILABLE,
    )

    summary = aggregate_handoff_tokens([measured, unmeasured])

    assert summary.measured_total_tokens == 150
    assert summary.measured_handoff_count == 1
    assert summary.unavailable_handoff_count == 1
    assert summary.handoff_count == 2
    assert summary.tokens_complete is False


def test_telemetry_to_dict_is_serializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    payload = response.to_telemetry_dict()
    assert payload["run_id"] == response.run_id
    assert len(payload["handoff_telemetry"]) == 2
    first = payload["handoff_telemetry"][0]
    for key in (
        "source_agent",
        "destination_agent",
        "task",
        "task_id",
        "question",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "latency_ms",
        "success",
        "error",
        "token_source",
    ):
        assert key in first
    assert payload["token_summary"]["handoff_count"] == 2


def test_core_orchestration_behavior_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry must be purely additive: answers and flow are identical."""
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question="How do I create an order in v3?", config=BenchmarkConfig())
    )

    assert response.success is True
    assert response.errors == []
    assert response.version_evidence.supported is True
    assert response.code_response is not None
    assert response.code_response.supported is True
    assert response.code_response.has_code is True
    assert 'Strategy(version="v3")' in response.answer
    assert [h.task for h in response.handoffs] == [
        "version_deprecation_analysis",
        "code_sample_generation",
    ]
    assert len(response.worker_handoffs) == 2
    assert response.latency_ms > 0.0


# ==========================================================================
# Week 10 context re-send accounting
# ==========================================================================

QUESTION = "How do I create an order in v3?"


def test_context_tokens_use_project_convention() -> None:
    # Matches the len(text) // 4 convention used by agent_loop.py.
    assert project_chars_div_4("") == 0
    assert project_chars_div_4("abcd") == 1
    assert project_chars_div_4("a" * 400) == 100
    assert project_chars_div_4("a" * 31) == 7


def test_version_handoff_context_is_the_question_only() -> None:
    # 31 chars // 4 == 7. No config object, callable or control int is counted.
    assert project_chars_div_4(QUESTION) == 7


def test_code_handoff_context_includes_forwarded_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question=QUESTION, config=BenchmarkConfig())
    )

    record = _telemetry_by_task(response, "code_sample_generation")
    # question (7) + one evidence chunk of 221 chars (55)
    assert record.handoff_context_tokens == 7 + 55
    assert record.handoff_context_tokens > _telemetry_by_task(
        response, "version_deprecation_analysis"
    ).handoff_context_tokens


def test_context_tokens_are_measured_while_provider_tokens_stay_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two concepts must never be conflated."""
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question=QUESTION, config=BenchmarkConfig())
    )

    for record in response.handoff_telemetry:
        # Measured context...
        assert record.handoff_context_tokens > 0
        assert record.context_token_method == CONTEXT_TOKEN_METHOD_CHARS_DIV_4
        assert record.context_tokens_estimated is True
        # ...while provider usage remains unavailable, never zero-filled.
        assert record.token_source == TOKEN_SOURCE_UNAVAILABLE
        assert record.input_tokens is None
        assert record.output_tokens is None
        assert record.total_tokens is None


def test_context_resend_counts_the_question_once_per_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-sending the question to both workers is the measured phenomenon."""
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question=QUESTION, config=BenchmarkConfig())
    )

    per_handoff = [t.handoff_context_tokens for t in response.handoff_telemetry]
    assert per_handoff[0] == 7
    assert per_handoff[1] == 7 + 55
    assert response.token_summary.total_context_tokens == sum(per_handoff)


def test_context_resend_summary_excludes_provider_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION)

    response = orchestrator.run(
        SquadRequest(question=QUESTION, config=BenchmarkConfig())
    )

    summary = response.token_summary
    # Provider totals stay at zero because nothing was measured...
    assert summary.measured_total_tokens == 0
    assert summary.tokens_complete is False
    # ...and are NOT folded into the context figure.
    assert summary.total_context_tokens > 0
    assert summary.total_context_tokens != summary.measured_total_tokens


def test_context_resend_multiplier_math() -> None:
    summary = aggregate_handoff_tokens(
        [
            HandoffTelemetry(task="a", handoff_context_tokens=100),
            HandoffTelemetry(task="b", handoff_context_tokens=150),
        ]
    )
    assert summary.total_context_tokens == 250
    assert summary.context_resend_multiplier(500) == 0.5


def test_context_resend_multiplier_refuses_bad_denominator() -> None:
    summary = aggregate_handoff_tokens([HandoffTelemetry(task="a", handoff_context_tokens=100)])
    # Never fabricate infinity or zero when the Single Agent total is unusable.
    assert summary.context_resend_multiplier(0) is None
    assert summary.context_resend_multiplier(-5) is None


def test_context_counter_is_pluggable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real tokenizer can replace the heuristic without touching call sites."""

    def fake_tokenizer(text: str) -> int:
        return len(text.split())

    _patch_tools(monkeypatch)
    orchestrator = ManagerOrchestrator(lambda: COLLECTION, context_counter=fake_tokenizer)

    response = orchestrator.run(
        SquadRequest(question=QUESTION, config=BenchmarkConfig())
    )

    record = _telemetry_by_task(response, "version_deprecation_analysis")
    assert record.handoff_context_tokens == len(QUESTION.split())
    assert record.handoff_context_tokens != project_chars_div_4(QUESTION)


def test_count_context_tokens_skips_empty_parts() -> None:
    assert count_context_tokens(["abcd", "", None or ""], project_chars_div_4) == 1
    assert count_context_tokens([], project_chars_div_4) == 0


# ==========================================================================
# Week 10 head-to-head race runner
# ==========================================================================


class _FakeState:
    def __init__(self, answer: str) -> None:
        self.answer = answer


class _FakeSquad:
    """Stand-in for SquadResponse with the same field surface."""

    def __init__(self, question: str, correct: bool) -> None:
        from telemetry.telemetry import ExecutionTelemetry
        from telemetry.week10_handoff import (
            HandoffTelemetry,
            HandoffTokenSummary,
            aggregate_handoff_tokens,
        )

        self.answer = f"answer for {question}"
        self.success = correct
        self.errors: list[str] = []
        self.latency_ms = 12.5
        self.code_response = None
        records = [
            HandoffTelemetry(
                run_id="r1",
                sequence=0,
                source_agent="manager_orchestrator",
                destination_agent="version_deprecation_worker",
                task="version_deprecation_analysis",
                question=question,
                handoff_context_tokens=7,
                success=True,
                tool_calls=3,
            ),
            HandoffTelemetry(
                run_id="r1",
                sequence=1,
                source_agent="manager_orchestrator",
                destination_agent="code_sample_worker",
                task="code_sample_generation",
                question=question,
                handoff_context_tokens=62,
                success=True,
                tool_calls=0,
            ),
        ]
        self.handoff_telemetry = records
        self.token_summary = aggregate_handoff_tokens(records)


def _fake_single_runner_factory(latencies: dict[str, float]):
    from telemetry.telemetry import ExecutionTelemetry

    def _run(question: str, config: Any, collection_name: str):
        # Answer text that satisfies the shared evaluator for positive cases.
        answer = "Information not provided in the supplied reference context."
        lat = latencies.get(question, 5.0)
        tel = ExecutionTelemetry(
            architecture="agent",
            latency_ms=lat,
            input_tokens=100,
            output_tokens=40,
            estimated_cost_usd=0.001,
            answer=answer,
        )
        return _FakeState(answer), None, tel

    return _run


def _fake_multi_runner_factory(correct_every: bool = True):
    def _run(question: str, config: Any, collection_name: str):
        return _FakeSquad(question, correct_every)

    return _run


@pytest.fixture()
def race_config() -> BenchmarkConfig:
    return BenchmarkConfig()


# ── 1. exactly the 10 required cases ──────────────────────────────────────


def test_exactly_the_ten_required_cases_are_declared() -> None:
    assert WEEK10_CASE_IDS == [
        "easy:01",
        "easy:04",
        "easy:13",
        "medium:02",
        "medium:05",
        "medium:14",
        "hard:01",
        "hard:04",
        "hard:09",
        "hard:13",
    ]
    assert len(WEEK10_CASE_IDS) == 10
    assert len(set(WEEK10_CASE_IDS)) == 10


def test_selection_resolves_exactly_ten_entries(race_config: BenchmarkConfig) -> None:
    entries = select_week10_cases(race_config)
    assert len(entries) == 10
    resolved = [f"{e.level.lower()}:{e.id}" for e in entries]
    assert resolved == WEEK10_CASE_IDS


def test_selection_rejects_a_case_that_does_not_exist(race_config: BenchmarkConfig) -> None:
    with pytest.raises(ValueError):
        select_week10_cases(race_config, ["easy:99"])


def test_race_result_case_ids_match_the_required_set(race_config: BenchmarkConfig) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )
    assert result.case_ids == WEEK10_CASE_IDS


# ── 2. both arms receive the same cases ───────────────────────────────────


def test_both_arms_receive_identical_cases(race_config: BenchmarkConfig) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    assert len(result.single_agent_cases) == 10
    assert len(result.multi_agent_cases) == 10

    single_ids = [c.case_id for c in result.single_agent_cases]
    multi_ids = [c.case_id for c in result.multi_agent_cases]
    assert single_ids == multi_ids == WEEK10_CASE_IDS

    # Identical question text per case -> no arm-specific case selection.
    for s, m in zip(result.single_agent_cases, result.multi_agent_cases):
        assert s.question == m.question
        assert s.level == m.level


def test_multi_agent_arm_receives_no_extra_cases(race_config: BenchmarkConfig) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )
    assert len(result.multi_agent_cases) == len(result.single_agent_cases) == 10


def test_both_arms_receive_the_same_questions_at_call_time(
    race_config: BenchmarkConfig,
) -> None:
    single_seen: list[str] = []
    multi_seen: list[str] = []

    def single_run(q: str, config: Any, collection_name: str):
        single_seen.append(q)
        return _fake_single_runner_factory({})(q, config, collection_name)

    def multi_run(q: str, config: Any, collection_name: str):
        multi_seen.append(q)
        return _FakeSquad(q, True)

    run_week10_race(
        race_config,
        single_runner=single_run,
        multi_runner=multi_run,
        verbose=False,
    )

    assert len(single_seen) == 10
    assert single_seen == multi_seen


# ── 3. both arms use the existing evaluator ───────────────────────────────


def test_both_arms_use_the_existing_evaluator(
    race_config: BenchmarkConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    real_evaluate = wrr.evaluate_answer

    def _spy(entry, answer, telemetry):
        calls.append(entry.id)
        return real_evaluate(entry, answer, telemetry)

    monkeypatch.setattr(wrr, "evaluate_answer", _spy)

    run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    # 10 cases x 2 arms, all through the one shared evaluator.
    assert len(calls) == 20
    assert set(calls) == {e.id for e in select_week10_cases(race_config)}


def test_race_runner_does_not_define_a_second_evaluator() -> None:
    import eval.evaluator as real_evaluator

    assert wrr.evaluate_answer is real_evaluator.evaluate_answer
    assert not hasattr(wrr, "evaluate")


# ── 4. aggregate metrics come from actual per-case results ────────────────


def test_aggregate_metrics_are_computed_from_per_case_results(
    race_config: BenchmarkConfig,
) -> None:
    latencies = {
        e.question: float(i + 1) * 10.0
        for i, e in enumerate(select_week10_cases(race_config))
    }
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory(latencies),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    sa = result.single_agent_metrics
    raw_latencies = [c.latency_ms for c in result.single_agent_cases]

    # Recompute independently from the preserved raw results.
    assert sa.total_cases == len(raw_latencies) == 10
    assert sa.passed == sum(1 for c in result.single_agent_cases if c.is_correct)
    assert sa.pass_rate == sa.passed / 10 * 100
    assert sa.p50_latency_ms == pytest.approx(statistics.median(raw_latencies))
    assert sa.p99_latency_ms == pytest.approx(max(raw_latencies))
    assert sa.total_cost_usd == pytest.approx(
        sum(c.cost_usd for c in result.single_agent_cases)
    )
    assert sa.cost_per_question_usd == pytest.approx(sa.total_cost_usd / 10)


def test_pass_rate_reflects_actual_correctness(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(correct_every=False),
        verbose=False,
    )

    ma = result.multi_agent_metrics
    raw_passes = sum(1 for c in result.multi_agent_cases if c.is_correct)
    assert ma.passed == raw_passes
    assert ma.pass_rate == pytest.approx(raw_passes / 10 * 100)


def test_percentile_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert wrr._percentile_nearest_rank(values, 99) == 10.0
    assert wrr._percentile_nearest_rank(values, 50) == 5.0
    assert wrr._percentile_nearest_rank([], 99) == 0.0


def test_crashed_arm_is_recorded_not_swallowed(race_config: BenchmarkConfig) -> None:
    def boom(q: str, config: Any, collection_name: str):
        raise RuntimeError("arm exploded")

    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=boom,
        verbose=False,
    )

    assert all(c.is_correct is False for c in result.multi_agent_cases)
    assert all(c.error == "arm exploded" for c in result.multi_agent_cases)
    assert result.multi_agent_metrics.pass_rate == 0.0


# ── 5. multi-agent context-token summary is preserved ─────────────────────


def test_multi_agent_context_token_summary_is_preserved(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    h = result.multi_agent_handoffs
    # 10 cases x (7 + 62)
    assert h.total_context_tokens == 10 * (7 + 62)
    assert h.total_context_tokens == result.multi_agent_metrics.total_context_tokens
    assert h.context_token_method == CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    assert h.context_tokens_estimated is True

    assert h.total_handoffs == 20
    assert h.successful_handoffs == 20
    assert h.failed_handoffs == 0
    assert set(h.by_destination) == {
        "version_deprecation_worker",
        "code_sample_worker",
    }


def test_per_handoff_records_are_preserved_verbatim(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    case = result.multi_agent_cases[0]
    assert len(case.handoff_telemetry) == 2
    first = case.handoff_telemetry[0]
    for key in (
        "source_agent",
        "destination_agent",
        "task",
        "handoff_context_tokens",
        "context_token_method",
        "context_tokens_estimated",
        "success",
        "latency_ms",
        "tool_calls",
    ):
        assert key in first
    assert case.worker_tool_calls == 3


def test_real_context_tokens_flow_through_the_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: real orchestrator + real tools, real context accounting."""
    _patch_tools(monkeypatch)
    seen: list[str] = []

    def multi_run(question: str, config: Any, collection_name: str):
        seen.append(question)
        return ManagerOrchestrator(lambda: collection_name).run(
            SquadRequest(question=question, config=config, collection_name=collection_name)
        )

    result = run_week10_race(
        BenchmarkConfig(),
        single_runner=_fake_single_runner_factory({}),
        multi_runner=multi_run,
        verbose=False,
    )

    assert len(seen) == 10
    assert result.multi_agent_handoffs.total_context_tokens > 0
    assert result.multi_agent_handoffs.context_token_method == CONTEXT_TOKEN_METHOD_CHARS_DIV_4
    for case in result.multi_agent_cases:
        assert case.total_context_tokens > 0
        assert case.handoff_count == 2


# ── 6. provider-token None values are not converted to zero ───────────────


def test_provider_tokens_stay_none_for_multi_agent(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    for case in result.multi_agent_cases:
        assert case.provider_input_tokens is None
        assert case.provider_output_tokens is None
        assert case.provider_total_tokens is None

    ma = result.multi_agent_metrics
    assert ma.provider_total_tokens is None
    assert ma.provider_tokens_available is False


def test_single_agent_provider_tokens_are_preserved(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    for case in result.single_agent_cases:
        assert case.provider_input_tokens == 100
        assert case.provider_output_tokens == 40
        assert case.provider_total_tokens == 140

    sa = result.single_agent_metrics
    assert sa.provider_total_tokens == 10 * 140
    assert sa.provider_tokens_available is True


def test_multi_agent_context_tokens_are_not_folded_into_provider_tokens(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    ma = result.multi_agent_metrics
    assert ma.provider_total_tokens is None
    assert ma.total_context_tokens > 0
    assert ma.total_context_tokens != ma.provider_total_tokens


def test_context_resend_multiplier_uses_context_not_provider_tokens(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    multiplier = result.context_resend_multiplier(
        result.single_agent_metrics.provider_total_tokens
    )
    assert multiplier == pytest.approx(10 * 69 / (10 * 140))
    assert result.context_resend_multiplier(0) is None
    assert result.context_resend_multiplier(None) is None


# ── 7. no failure injection during the normal race ────────────────────────


def test_normal_race_has_no_failure_injection(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )
    assert result.failure_injection_enabled is False
    assert result.to_dict()["failure_injection_enabled"] is False


def test_race_runner_exposes_no_injection_hook() -> None:
    import inspect

    signature = inspect.signature(run_week10_race)
    for forbidden in (
        "inject_failure",
        "failure_injection",
        "http_500",
        "fail_worker",
        "inject",
    ):
        assert forbidden not in signature.parameters


def test_clean_race_reports_zero_handoff_failures(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )
    assert result.multi_agent_handoffs.failed_handoffs == 0
    assert all(not c.handoff_errors for c in result.multi_agent_cases)


# ── serialization ──────────────────────────────────────────────────────────


def test_race_result_serializes_for_later_artifacts(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )

    payload = result.to_dict()
    for key in (
        "case_ids",
        "single_agent_cases",
        "multi_agent_cases",
        "single_agent_metrics",
        "multi_agent_metrics",
        "multi_agent_handoffs",
        "context_resend_multiplier",
        "failure_injection_enabled",
    ):
        assert key in payload
    assert len(payload["single_agent_cases"]) == 10
    assert len(payload["multi_agent_cases"]) == 10


def test_race_summary_formats_without_writing_files(
    race_config: BenchmarkConfig,
) -> None:
    result = run_week10_race(
        race_config,
        single_runner=_fake_single_runner_factory({}),
        multi_runner=_fake_multi_runner_factory(),
        verbose=False,
    )
    text = wrr.format_race_summary(result)
    assert "project_chars_div_4" in text
    assert "unavailable" in text
    assert "single_agent" in text and "multi_agent" in text