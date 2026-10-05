"""
app/routes/benchmark.py
-----------------------
POST /api/benchmark/run         — Run the standardised Week 7 "Agent vs
Deterministic Workflow" benchmark (10 scenarios) through the existing ``eval``
package.
POST /api/benchmark/week10/race — Run the Week 10 "Single Agent vs Multi-Agent
Squad" race through the existing ``eval.week10_race_runner``.

Both endpoints are thin wrappers: they do NOT re-implement any evaluation or
scoring logic, golden-set handling, or agent/workflow behaviour. They simply
invoke the existing runners (the same entry points used by ``eval/run_benchmark.py``
and the Week 10 race CLI) and serialise the results for the UI.

The handlers are deliberately synchronous (blocking CPU work) so FastAPI executes
them in its threadpool instead of stalling the event loop — the same pattern used
by the MRR evaluation endpoint. Each benchmark's own safety controls (iteration /
token / cost / time budgets) are preserved inside its runner.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from benchmark.config import load_config_from_env
from eval.benchmark_runner import run_benchmark
from eval.week10_race_runner import run_week10_race

router = APIRouter(prefix="/api/benchmark", tags=["Benchmark"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class BenchmarkRunRequest(BaseModel):
    scenario_ids: list[str] | None = Field(
        default=None,
        description="Scenario IDs to run, e.g. ['easy:01', 'easy:04', ...]. "
        "Defaults to the standard 10-scenario benchmark set.",
    )


class BenchmarkMetricsOut(BaseModel):
    architecture: str
    success_rate: float
    successful_count: int
    total_count: int
    p50_latency_ms: float
    p99_latency_ms: float
    avg_input_tokens: float
    avg_output_tokens: float
    avg_total_tokens: float
    total_tokens: int
    total_cost_usd: float
    avg_cost_per_run: float
    cost_per_success: float


class ScenarioResultOut(BaseModel):
    id: str
    level: str
    is_negative_case: bool
    question: str
    agent_correct: bool
    agent_match_type: str
    workflow_correct: bool
    workflow_match_type: str


class BenchmarkRunResponse(BaseModel):
    scenario_ids: list[str]
    agent: BenchmarkMetricsOut
    workflow: BenchmarkMetricsOut
    scenario_results: list[ScenarioResultOut]


class Week10RaceRequest(BaseModel):
    case_ids: list[str] | None = Field(
        default=None,
        description="Optional case IDs to run, e.g. ['easy:01', 'hard:01', ...]. "
        "Defaults to the sanctioned Week 10 10-case set. The race expects the "
        "requested count to resolve exactly, so the two arms cannot diverge.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _metrics_out(metrics: object) -> BenchmarkMetricsOut:
    """Shim a ``BenchmarkMetrics`` dataclass instance onto the response model."""
    return BenchmarkMetricsOut(**vars(metrics))


def _scenario_result_out(result: object) -> ScenarioResultOut:
    """Shim a ``ScenarioResult`` onto the response model."""
    entry = result.entry
    agent_eval = result.agent_eval
    workflow_eval = result.workflow_eval
    return ScenarioResultOut(
        id=entry.id,
        level=entry.level,
        is_negative_case=entry.is_negative_case,
        question=entry.question,
        agent_correct=bool(agent_eval and agent_eval.is_correct),
        agent_match_type=agent_eval.match_type if agent_eval else "error",
        workflow_correct=bool(workflow_eval and workflow_eval.is_correct),
        workflow_match_type=workflow_eval.match_type if workflow_eval else "error",
    )


# Deliberately sync: run_benchmark does blocking CPU work (embedding + retrieval
# across every scenario), so FastAPI runs it in a threadpool.
@router.post(
    "/run",
    response_model=BenchmarkRunResponse,
    summary="Run the Agent vs Workflow benchmark",
)
def run_benchmark_api(
    body: BenchmarkRunRequest | None = None,
) -> BenchmarkRunResponse:
    """
    Execute the existing standardised 10-scenario benchmark and return the
    agent/workflow comparison for the UI.

    No request body is required. ``scenario_ids`` may override the default
    scenario selection (used mainly for diagnostics).
    """
    config = load_config_from_env()
    scenario_ids = body.scenario_ids if body and body.scenario_ids else None

    try:
        output = run_benchmark(config, scenario_ids=scenario_ids, verbose=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {exc}") from exc

    return BenchmarkRunResponse(
        scenario_ids=list(output.scenario_ids),
        agent=_metrics_out(output.agent_metrics),
        workflow=_metrics_out(output.workflow_metrics),
        scenario_results=[_scenario_result_out(r) for r in output.scenario_results],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Week 10 — Single Agent vs Multi-Agent Squad
# ─────────────────────────────────────────────────────────────────────────────
#
# This is the HTTP transport adapter for the existing Week 10 experiment and
# nothing more. It intentionally:
#
#   * calls the existing ``eval.week10_race_runner.run_week10_race`` entry point,
#     which remains the single source of truth for case selection, orchestration,
#     scoring, token accounting and telemetry;
#   * returns ``RaceResult.to_dict()`` verbatim, so there is exactly one
#     representation of a race rather than a second, API-shaped copy;
#   * computes no metrics of its own and hardcodes no Week 10 figures.
#
# Unavailable provider tokens stay ``null`` on the wire (``None`` is preserved,
# never coerced to 0) because the Multi-Agent workers make no LLM calls. The
# published Week 10 verdict is a documented experiment conclusion, not an output
# of this route, and is therefore absent from the response.
#
# Deliberately sync, for the same reason as /run above.

@router.post(
    "/week10/race",
    summary="Run the Week 10 Single Agent vs Multi-Agent Squad race",
)
def run_week10_race_api(
    body: Week10RaceRequest | None = None,
) -> dict[str, Any]:
    """
    Execute the existing Week 10 race and return ``RaceResult.to_dict()``.

    No request body is required. ``case_ids`` may override the default Week 10
    10-case selection (used mainly for diagnostics).
    """
    config = load_config_from_env()
    case_ids = body.case_ids if body and body.case_ids else None

    try:
        result = run_week10_race(config, case_ids=case_ids, verbose=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Week 10 race failed: {exc}"
        ) from exc

    return result.to_dict()