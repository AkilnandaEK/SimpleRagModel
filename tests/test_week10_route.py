"""
tests/test_week10_route.py
--------------------------
Focused HTTP-boundary tests for ``POST /api/benchmark/week10/race``.

Scope: these tests assert only that the FastAPI adapter is a faithful transport
for the existing Week 10 experiment. They never execute the real race -- that is
expensive and belongs to the experiment's own test suite. Instead they mock at
the route boundary (``app.routes.benchmark.run_week10_race``) and feed back real
``RaceResult`` instances built from the genuine result dataclasses, so the
assertions exercise the true ``to_dict()`` shape.

Protected: nothing in ``eval/``, ``agent/``, ``telemetry/`` or ``benchmark/`` is
modified by this module. The route is only ever tested as a transport.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import benchmark as benchmark_routes
from eval.week10_race_runner import (
    ARM_MULTI,
    ARM_SINGLE,
    ArmMetrics,
    CaseResult,
    MultiAgentHandoffSummary,
    RaceResult,
)

RACE_PATH = "/api/benchmark/week10/race"


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_race_result(
    *,
    single_provider_tokens: int | None = 2024,
    multi_provider_tokens: int | None = None,
    context_resend: int = 3964,
) -> RaceResult:
    """Build a real ``RaceResult`` mirroring the recorded Week 10 semantics.

    ``multi_provider_tokens=None`` reproduces the important case: the Multi-Agent
    workers make no LLM calls, so provider tokens are genuinely unavailable and
    must stay ``None`` all the way to the JSON payload.
    """
    # Token accounting is all-or-nothing per arm (mirrors _compute_arm_metrics).
    if single_provider_tokens is None:
        single_in_1 = single_out_1 = single_in_2 = single_out_2 = None
    else:
        single_in_1 = int(single_provider_tokens * 0.74)
        single_out_1 = single_provider_tokens - single_in_1
        single_in_2, single_out_2 = 0, 0

    single_cases = [
        CaseResult(
            case_id="easy:01",
            arm=ARM_SINGLE,
            level="easy",
            question="q1",
            is_correct=True,
            match_type="exact",
            answer="a1",
            latency_ms=19.58,
            provider_input_tokens=single_in_1,
            provider_output_tokens=single_out_1,
            cost_usd=0.000546,
        ),
        CaseResult(
            case_id="hard:01",
            arm=ARM_SINGLE,
            level="hard",
            question="q2",
            is_correct=False,
            match_type="none",
            answer="",
            latency_ms=35.97,
            provider_input_tokens=single_in_2,
            provider_output_tokens=single_out_2,
            cost_usd=0.0,
        ),
    ]

    multi_cases = [
        CaseResult(
            case_id="easy:01",
            arm=ARM_MULTI,
            level="easy",
            question="q1",
            is_correct=True,
            match_type="exact",
            answer="a1",
            latency_ms=21.4,
            # No LLM call -> no provider token accounting.
            provider_input_tokens=multi_provider_tokens,
            provider_output_tokens=multi_provider_tokens,
            cost_usd=0.0,
            handoff_count=2,
            successful_handoffs=2,
            failed_handoffs=0,
            total_context_tokens=context_resend,
            handoff_telemetry=[
                {
                    "destination_agent": "Code-Sample Worker",
                    "success": True,
                    "handoff_context_tokens": 3674,
                },
                {
                    "destination_agent": "Version/Deprecation Worker",
                    "success": True,
                    "handoff_context_tokens": 290,
                },
            ],
            worker_tool_calls=4,
            worker_llm_calls=0,
        ),
        CaseResult(
            case_id="hard:01",
            arm=ARM_MULTI,
            level="hard",
            question="q2",
            is_correct=False,
            match_type="none",
            answer="",
            latency_ms=26.83,
            provider_input_tokens=multi_provider_tokens,
            provider_output_tokens=multi_provider_tokens,
            cost_usd=0.0,
            handoff_count=0,
            successful_handoffs=0,
            failed_handoffs=0,
            total_context_tokens=0,
            worker_tool_calls=0,
            worker_llm_calls=0,
        ),
    ]

    handoff_summary = MultiAgentHandoffSummary(
        total_handoffs=2,
        successful_handoffs=2,
        failed_handoffs=0,
        by_destination={
            "Code-Sample Worker": {
                "total": 1,
                "success": 1,
                "failed": 0,
                "context_tokens": 3674,
            },
            "Version/Deprecation Worker": {
                "total": 1,
                "success": 1,
                "failed": 0,
                "context_tokens": 290,
            },
        },
        total_context_tokens=context_resend,
    )

    def _arm(arm: str, cases: list[CaseResult]) -> ArmMetrics:
        latencies = [c.latency_ms for c in cases]
        measured = [c for c in cases if c.provider_total_tokens is not None]
        # Mirrors _compute_arm_metrics: all-or-nothing availability.
        total = (
            sum(int(c.provider_total_tokens) for c in measured)
            if measured and len(measured) == len(cases)
            else None
        )
        passed = sum(1 for c in cases if c.is_correct)
        return ArmMetrics(
            arm=arm,
            total_cases=len(cases),
            passed=passed,
            failed=len(cases) - passed,
            pass_rate=passed / len(cases) * 100,
            p50_latency_ms=latencies[0],
            p99_latency_ms=latencies[-1],
            provider_total_tokens=total,
            provider_tokens_available=total is not None,
            total_context_tokens=sum(c.total_context_tokens for c in cases),
            total_cost_usd=sum(c.cost_usd for c in cases),
            cost_per_question_usd=sum(c.cost_usd for c in cases) / len(cases),
            total_handoffs=sum(c.handoff_count for c in cases),
            successful_handoffs=sum(c.successful_handoffs for c in cases),
            failed_handoffs=sum(c.failed_handoffs for c in cases),
        )

    return RaceResult(
        case_ids=["easy:01", "hard:01"],
        single_agent_cases=single_cases,
        multi_agent_cases=multi_cases,
        single_agent_metrics=_arm(ARM_SINGLE, single_cases),
        multi_agent_metrics=_arm(ARM_MULTI, multi_cases),
        multi_agent_handoffs=handoff_summary,
        failure_injection_enabled=False,
    )


@pytest.fixture
def client() -> TestClient:
    """A minimal app exposing only the benchmark router.

    Deliberately avoids importing ``app.main`` so these tests do not trigger the
    real lifespan (embedding model / Chroma warm-up). Router registration in the
    real app is asserted separately below.
    """
    app = FastAPI()
    app.include_router(benchmark_routes.router)
    return TestClient(app)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the runner at the route boundary and record how it was called."""
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"calls": calls, "result": _make_race_result()}

    def _fake_run_week10_race(config: Any, case_ids: Any = None, verbose: Any = False) -> RaceResult:
        calls.append({"config": config, "case_ids": case_ids, "verbose": verbose})
        return state["result"]

    monkeypatch.setattr(benchmark_routes, "run_week10_race", _fake_run_week10_race)
    return state


# ── Route existence and wiring ───────────────────────────────────────────────


def test_route_exists_and_is_post() -> None:
    """The adapter is registered as POST on the benchmark router."""
    methods = {
        route.path: route.methods
        for route in benchmark_routes.router.routes
        if getattr(route, "path", None) == RACE_PATH
    }
    assert RACE_PATH in methods, f"{RACE_PATH} not registered"
    assert "POST" in methods[RACE_PATH]


def test_route_registered_in_real_app() -> None:
    """The real application exposes the endpoint (router is included).

    Asserted through the OpenAPI schema rather than ``app.routes``: this
    FastAPI version keeps ``include_router`` results as ``_IncludedRouter``
    wrappers instead of flattening them into ``app.routes``.
    """
    from app.main import app

    paths = app.openapi()["paths"]
    assert RACE_PATH in paths, f"{RACE_PATH} not exposed by the application"
    assert "post" in paths[RACE_PATH]


def test_existing_benchmark_run_route_still_present() -> None:
    """The Week 7 Agent-vs-Workflow endpoint is untouched."""
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/benchmark/run" in paths
    assert "post" in paths["/api/benchmark/run"]


# ── Serialisation contract ───────────────────────────────────────────────────


def test_route_invokes_existing_runner(client: TestClient, captured: dict[str, Any]) -> None:
    """The HTTP request reaches ``run_week10_race`` exactly once."""
    response = client.post(RACE_PATH)

    assert response.status_code == 200
    assert len(captured["calls"]) == 1, "run_week10_race was not invoked exactly once"
    assert captured["calls"][0]["case_ids"] is None
    assert captured["calls"][0]["verbose"] is False


def test_response_serialises_race_result_to_dict(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """The payload is ``RaceResult.to_dict()`` verbatim -- one representation."""
    response = client.post(RACE_PATH)
    body = response.json()

    assert body == captured["result"].to_dict()


def test_case_ids_override_is_passed_through(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """An explicit case selection reaches the runner unchanged."""
    response = client.post(RACE_PATH, json={"case_ids": ["easy:01", "hard:01"]})

    assert response.status_code == 200
    assert captured["calls"][0]["case_ids"] == ["easy:01", "hard:01"]


def test_response_is_json_compatible(client: TestClient, captured: dict[str, Any]) -> None:
    """Every value survives a JSON round-trip (no dataclasses or NaN leaking)."""
    body = client.post(RACE_PATH).json()

    encoded = json.dumps(body)
    assert json.loads(encoded) == body

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert isinstance(key, str)
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        else:
            assert node is None or isinstance(node, (str, int, float, bool)), node

    _walk(body)


# ── Token semantics ──────────────────────────────────────────────────────────


def test_multi_agent_provider_tokens_remain_unavailable(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """Multi-Agent provider tokens stay ``null`` -- never coerced to 0."""
    body = client.post(RACE_PATH).json()
    multi = body["multi_agent_metrics"]

    assert multi["provider_total_tokens"] is None, "unavailable tokens became a value"
    assert multi["provider_tokens_available"] is False
    # A valid $0 cost is distinct from unavailable token accounting.
    assert multi["total_cost_usd"] == 0.0

    for case in body["multi_agent_cases"]:
        assert case["provider_total_tokens"] is None
        assert case["worker_llm_calls"] == 0

    assert body["multi_agent_handoffs"]["provider_tokens_available"] is False
    assert "unavailable" in body["multi_agent_handoffs"]["provider_token_note"].lower()


def test_single_agent_provider_tokens_are_reported(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """Real provider tokens for the LLM-calling arm survive serialisation."""
    single = client.post(RACE_PATH).json()["single_agent_metrics"]

    assert single["provider_total_tokens"] == 2024
    assert single["provider_tokens_available"] is True


def test_context_token_estimate_and_multiplier_are_exposed(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """Context re-send volume keeps its estimate semantics and multiplier."""
    body = client.post(RACE_PATH).json()

    assert body["multi_agent_handoffs"]["total_context_tokens"] == 3964
    assert body["multi_agent_handoffs"]["context_tokens_estimated"] is True
    assert body["multi_agent_handoffs"]["context_token_method"] == "project_chars_div_4"

    # 3964 / 2024
    assert body["context_resend_multiplier"] == pytest.approx(1.958498, rel=1e-5)


def test_context_resend_multiplier_is_null_without_a_denominator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    """No Single Agent provider tokens -> multiplier is ``null``, not 0 or inf."""
    captured["result"] = _make_race_result(single_provider_tokens=None)

    body = client.post(RACE_PATH).json()
    assert body["context_resend_multiplier"] is None


# ── No hardcoded results in the transport ────────────────────────────────────


def test_route_does_not_hardcode_week10_figures(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """The payload tracks the runner, so no Week 10 figure lives in the route."""
    baseline = client.post(RACE_PATH).json()
    assert baseline["multi_agent_handoffs"]["total_context_tokens"] == 3964

    captured["result"] = _make_race_result(
        single_provider_tokens=10, context_resend=99
    )
    changed = client.post(RACE_PATH).json()

    assert changed["multi_agent_handoffs"]["total_context_tokens"] == 99
    assert changed["single_agent_metrics"]["provider_total_tokens"] == 10
    assert changed["context_resend_multiplier"] != baseline["context_resend_multiplier"]


# ── Handoff telemetry and per-case detail ────────────────────────────────────


def test_handoff_telemetry_is_present(client: TestClient, captured: dict[str, Any]) -> None:
    """Per-worker context distribution survives to the UI layer."""
    handoffs = client.post(RACE_PATH).json()["multi_agent_handoffs"]

    assert handoffs["total_handoffs"] == 2
    assert handoffs["successful_handoffs"] == 2
    assert handoffs["failed_handoffs"] == 0
    assert handoffs["by_destination"]["Code-Sample Worker"]["context_tokens"] == 3674
    assert handoffs["by_destination"]["Version/Deprecation Worker"]["context_tokens"] == 290


def test_per_case_results_are_present(client: TestClient, captured: dict[str, Any]) -> None:
    """Both arms' per-case outcomes are exposed for the comparison table."""
    body = client.post(RACE_PATH).json()

    assert body["case_ids"] == ["easy:01", "hard:01"]
    assert [c["case_id"] for c in body["single_agent_cases"]] == ["easy:01", "hard:01"]
    assert [c["case_id"] for c in body["multi_agent_cases"]] == ["easy:01", "hard:01"]
    assert body["single_agent_cases"][0]["is_correct"] is True
    assert body["multi_agent_cases"][0]["match_type"] == "exact"


def test_failure_injection_flag_is_false_for_clean_race(
    client: TestClient, captured: dict[str, Any]
) -> None:
    """The live endpoint runs the clean baseline, never the failure injection."""
    assert client.post(RACE_PATH).json()["failure_injection_enabled"] is False


# ── Error mapping ────────────────────────────────────────────────────────────


def test_missing_goldenset_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(config: Any, case_ids: Any = None, verbose: Any = False) -> RaceResult:
        raise FileNotFoundError("goldensets/week10 missing")

    monkeypatch.setattr(benchmark_routes, "run_week10_race", _raise)

    response = client.post(RACE_PATH)
    assert response.status_code == 404
    assert "goldensets/week10" in response.json()["detail"]


def test_bad_case_selection_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(config: Any, case_ids: Any = None, verbose: Any = False) -> RaceResult:
        raise ValueError("Week 10 race expects 2 cases, resolved 1")

    monkeypatch.setattr(benchmark_routes, "run_week10_race", _raise)

    response = client.post(RACE_PATH, json={"case_ids": ["easy:01"]})
    assert response.status_code == 400
    assert "resolved 1" in response.json()["detail"]


def test_unexpected_failure_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(config: Any, case_ids: Any = None, verbose: Any = False) -> RaceResult:
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr(benchmark_routes, "run_week10_race", _raise)

    response = client.post(RACE_PATH)
    assert response.status_code == 500
    assert "embedding model unavailable" in response.json()["detail"]


# ── Experiment protection ────────────────────────────────────────────────────


def test_route_module_does_not_import_or_duplicate_race_logic() -> None:
    """The adapter only transports; it defines no metrics of its own."""
    source = (
        benchmark_routes.__file__ and open(benchmark_routes.__file__, encoding="utf-8").read()
    )

    # No aggregation helpers beyond the pre-existing Week 7 shims.
    assert "def _compute_arm_metrics" not in source
    assert "def _percentile" not in source
    assert "select_week10_cases" not in source
    assert "evaluate_answer" not in source