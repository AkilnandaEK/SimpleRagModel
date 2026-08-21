"""
app/routes/evaluation.py
------------------------
GET /eval/mrr          — Score the golden set with MRR@k (optionally one split).
GET /eval/golden-set   — Return the golden set itself, without running retrieval.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.mrr import KNOWN_SPLITS, evaluate_mrr, load_golden_set

router = APIRouter(prefix="/eval", tags=["Evaluation"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class GoldenQueryOut(BaseModel):
    id: str
    question: str
    split: str
    expected_chunk_ids: list[str]
    sdk_version: str | None = None


class GoldenSetResponse(BaseModel):
    collection_name: str | None = None
    query_count: int
    splits: dict[str, int] = Field(default_factory=dict, description="Query count per split.")
    queries: list[GoldenQueryOut]


class QueryEvaluationOut(BaseModel):
    id: str
    question: str
    split: str
    expected_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    first_relevant_rank: int | None = None
    reciprocal_rank: float


class SplitScoreOut(BaseModel):
    split: str
    query_count: int
    mrr: float


class MrrReportResponse(BaseModel):
    collection_name: str
    top_k: int
    split: str | None = None
    query_count: int
    mrr: float
    split_scores: list[SplitScoreOut]
    evaluations: list[QueryEvaluationOut]
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal problems, e.g. some expected chunk IDs are absent.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _load() -> tuple[list, str | None]:
    """Load the configured golden set, mapping failures onto HTTP errors."""
    try:
        return load_golden_set(settings.golden_set_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid golden set: {exc}") from exc


@router.get("/golden-set", response_model=GoldenSetResponse, summary="Inspect the graded query set")
def get_golden_set() -> GoldenSetResponse:
    """Return the golden set and its split sizes without touching the retriever."""
    golden_set, default_collection = _load()

    splits: dict[str, int] = {}
    for name in KNOWN_SPLITS:
        count = sum(1 for query in golden_set if query.split == name)
        if count:
            splits[name] = count

    return GoldenSetResponse(
        collection_name=default_collection,
        query_count=len(golden_set),
        splits=splits,
        queries=[
            GoldenQueryOut(
                id=query.id,
                question=query.question,
                split=query.split,
                expected_chunk_ids=list(query.expected_chunk_ids),
                sdk_version=query.sdk_version,
            )
            for query in golden_set
        ],
    )


# Deliberately sync: evaluate_mrr is blocking CPU work (embedding + BM25), so
# FastAPI runs it in a threadpool instead of stalling the event loop.
@router.get("/mrr", response_model=MrrReportResponse, summary="Score the golden set with MRR@k")
def get_mrr(
    collection_name: str | None = Query(
        default=None,
        description="Collection to evaluate. Defaults to the golden set's collection_name.",
    ),
    top_k: int = Query(default=0, ge=0, description="Retrieval cutoff k (0 = settings.top_k)."),
    split: str | None = Query(
        default=None,
        description="Restrict to 'dev' or 'test'. Omit to score everything.",
    ),
) -> MrrReportResponse:
    """
    Run the golden set through the live hybrid retriever and return MRR@k, both
    overall and broken down per split.
    """
    golden_set, default_collection = _load()

    target_collection = collection_name or default_collection
    if not target_collection:
        raise HTTPException(
            status_code=400,
            detail="No collection specified and the golden set has no 'collection_name'.",
        )

    try:
        report = evaluate_mrr(target_collection, golden_set, top_k=top_k, split=split)
    except ValueError as exc:
        # Covers unknown/empty split and a missing collection.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"MRR evaluation failed: {exc}") from exc

    return MrrReportResponse(**report.to_dict())
