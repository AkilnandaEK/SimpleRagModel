"""
app/routes/benchmark.py
-----------------------
POST /api/benchmark/run  — Run the standardised Week 7 "Agent vs Deterministic
Workflow" benchmark (10 scenarios) through the existing ``eval`` package.

This endpoint is a thin wrapper: it does NOT re-implement any evaluation or
scoring logic, golden-set handling, or agent/workflow behaviour. It simply
invokes ``eval.benchmark_runner.run_benchmark`` (the same entry point used by
``eval/run_benchmark.py``) and serialises the resulting metrics for the UI.

The handler is deliberately synchronous (blocking CPU work) so FastAPI executes
it in its threadpool instead of stalling the event loop — the same pattern used
by the MRR evaluation endpoint. The benchmark's own safety controls (iteration /
token / cost / time budgets) are preserved inside the runner.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from benchmark.config import load_config_from_env
from eval.benchmark_runner import run_benchmark

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