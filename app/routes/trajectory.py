"""
app/routes/trajectory.py
------------------------
POST /api/trajectory/run  — Run the Week 8 trajectory evaluation suite.
GET  /api/trajectory/cases — Inspect the 10 declared trajectory contracts.
GET  /api/trajectory/taxonomy — The failure-mode taxonomy.

Like the Week 7 benchmark route, this is a thin wrapper: it re-implements no
scoring, no assertions and no agent behaviour. It invokes
``eval.trajectory_eval.run_trajectory_eval`` — the same entry point as
``python eval/trajectory_eval.py`` — and serialises the report for the UI.

Handlers are deliberately synchronous. The suite does blocking work (embedding,
retrieval and up to ~40 live LLM calls), so FastAPI runs it in its threadpool
instead of stalling the event loop.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from benchmark.config import load_config_from_env
from eval.trajectory_cases import FAILURE_MODES, load_trajectory_cases
from eval.trajectory_eval import run_trajectory_eval

router = APIRouter(prefix="/api/trajectory", tags=["Trajectory Eval"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class TrajectoryRunRequest(BaseModel):
    mode: str | None = Field(
        default=None,
        description=(
            "'live' runs the real LLM; 'offline' uses the deterministic "
            "reasoner. Offline cannot expose an outcome-vs-trajectory gap — the "
            "reasoner always walks the same path — so 'live' is the meaningful "
            "setting. Defaults to WEEK7_LLM_MODE."
        ),
    )
    provider: str | None = Field(
        default=None, description="'groq' or 'gemini'. Defaults to config."
    )
    model: str | None = Field(
        default=None, description="Model id override for the chosen provider."
    )
    include_injection: bool = Field(
        default=True,
        description="Run the indirect prompt-injection bonus suite.",
    )
    scenario_keys: list[str] | None = Field(
        default=None,
        description=(
            "Golden-set scenario keys to run, e.g. ['easy:01', 'hard:09']. "
            "Defaults to the standard ten. A short list keeps a run cheap — the "
            "full suite is roughly 145 LLM calls."
        ),
    )


class TrajectoryCaseOut(BaseModel):
    case_id: str
    scenario_key: str
    question: str
    kind: str
    allowed_paths: list[list[str]]
    required_tools: list[str]
    optimal_steps: int
    max_reasonable_steps: int


class FailureModeOut(BaseModel):
    code: str
    name: str
    description: str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/cases",
    response_model=list[TrajectoryCaseOut],
    summary="The 10 declared trajectory contracts",
)
def list_cases() -> list[TrajectoryCaseOut]:
    """Expose what each query is asserted against, without running anything.

    Questions come straight from the golden sets — this endpoint reflects
    whatever is in ``goldensets/`` right now.
    """
    config = load_config_from_env()
    return [
        TrajectoryCaseOut(
            case_id=c.case_id,
            scenario_key=c.scenario_key,
            question=c.question,
            kind=c.kind,
            allowed_paths=[list(p) for p in c.allowed_paths],
            required_tools=sorted(c.required_tools),
            optimal_steps=c.optimal_steps,
            max_reasonable_steps=c.max_reasonable_steps,
        )
        for c in load_trajectory_cases(config.golden_set_dir)
    ]


@router.get(
    "/taxonomy",
    response_model=list[FailureModeOut],
    summary="The failure-mode taxonomy",
)
def list_taxonomy() -> list[FailureModeOut]:
    return [
        FailureModeOut(code=m.code, name=m.name, description=m.description)
        for m in FAILURE_MODES
    ]


# Deliberately sync: run_trajectory_eval does blocking CPU + network work across
# every case, so FastAPI runs it in a threadpool.
@router.post(
    "/run",
    summary="Run the Week 8 trajectory evaluation suite",
)
def run_trajectory_api(body: TrajectoryRunRequest | None = None) -> dict[str, Any]:
    """
    Execute the full Week 8 suite: baseline trajectory run, gap analysis, the
    single mitigation experiment, the per-mode regression matrix, and (unless
    disabled) the prompt-injection bonus.

    Returns the same structure ``eval/trajectory_eval.py`` writes to disk. The
    response is left as a plain dict rather than a response_model so the UI sees
    the report verbatim — adding a Pydantic mirror here would be a second place
    to keep the schema in sync.
    """
    config = load_config_from_env()
    body = body or TrajectoryRunRequest()

    try:
        output = run_trajectory_eval(
            config,
            mode=body.mode,
            provider=body.provider,
            model_override=body.model,
            include_injection=body.include_injection,
            scenario_keys=tuple(body.scenario_keys) if body.scenario_keys else None,
            verbose=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Trajectory eval failed: {exc}"
        ) from exc

    return output.to_dict()
