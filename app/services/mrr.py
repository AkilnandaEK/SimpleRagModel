"""
app/services/mrr.py
-------------------
Mean Reciprocal Rank (MRR) evaluation for the hybrid retriever.

MRR answers exactly one question: *how high up the ranking is the FIRST
relevant chunk?*

    RR(query) = 1 / rank_of_first_relevant_chunk    (0.0 if none was retrieved)
    MRR       = mean(RR) across every graded query

Because the retriever is truncated at ``top_k``, this is strictly **MRR@k** — a
chunk that would have landed at rank k+1 scores 0.0, so the k you evaluated at
is part of the result and is always carried in the report.

MRR only credits the first hit. A query whose expected chunk sits at rank 1
scores 1.0; rank 2 scores 0.5; rank 5 scores 0.2. Adding a *second* relevant
chunk lower down changes nothing — that is the metric working as intended, not
a bug.

Splits
------
Every golden query carries a ``split``:

    dev   — tune against this freely (chunking, RRF_K, top_k, prompt)
    test  — held out; look at it only to confirm a change generalised

The report always carries a per-split breakdown, so a dev-set gain that does not
show up on test is visible immediately rather than being averaged away.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.core.config import settings
from app.services.embedder import embed_query
from app.services.hybrid_retrieval import hybrid_query_chunks
from app.services.vector_store import get_chunk_ids

#: Recognised split names. Validated at load time so a typo ("tset") fails loudly
#: instead of silently creating a third split nobody looks at.
KNOWN_SPLITS: tuple[str, ...] = ("dev", "test")

DEFAULT_SPLIT = "test"


# ─────────────────────────────────────────────────────────────────────────────
# Pure metric — no retrieval, no IO, trivially unit-testable
# ─────────────────────────────────────────────────────────────────────────────

def first_relevant_rank(retrieved_ids: Sequence[str], relevant_ids: Iterable[str]) -> int | None:
    """
    Return the 1-based position of the first relevant chunk, or None if the
    ranking contains no relevant chunk at all.

    Args:
        retrieved_ids: Chunk IDs in retrieved order (best first).
        relevant_ids: Chunk IDs considered correct for this query.
    """
    relevant = set(relevant_ids)
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant:
            return rank
    return None


def reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: Iterable[str]) -> float:
    """
    Reciprocal rank for a single query: 1/rank of the first relevant chunk.

    Returns 0.0 when nothing relevant was retrieved. Raises if the query has no
    relevant chunks defined — RR is undefined there, and silently scoring it 0.0
    would quietly drag the MRR down.
    """
    relevant = set(relevant_ids)
    if not relevant:
        raise ValueError("Reciprocal rank is undefined when no chunk is marked relevant.")

    rank = first_relevant_rank(retrieved_ids, relevant)
    return 0.0 if rank is None else 1.0 / rank


def mean_reciprocal_rank(reciprocal_ranks: Iterable[float]) -> float:
    """Average the per-query reciprocal ranks. Raises on an empty query set."""
    values = list(reciprocal_ranks)
    if not values:
        raise ValueError("MRR is undefined for an empty query set.")
    return sum(values) / len(values)


# ─────────────────────────────────────────────────────────────────────────────
# Golden set
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GoldenQuery:
    """One graded question: the query, the chunks that answer it, and its split."""

    id: str
    question: str
    expected_chunk_ids: tuple[str, ...]
    split: str = DEFAULT_SPLIT
    sdk_version: str | None = None


def parse_golden_set(payload: Any) -> tuple[list[GoldenQuery], str | None]:
    """
    Normalise a golden-set document into GoldenQuery objects.

    Accepts either a bare list of query objects, or a wrapper object:

        {"collection_name": "sdk-v3-strategy-a", "default_split": "test",
         "queries": [...]}

    Each query needs ``id``, ``question``, and either ``expected_chunk_ids``
    (list) or ``expected_chunk_id`` (single string). ``split`` is optional and
    falls back to the document's ``default_split``, then to "test".

    Returns:
        (queries, default_collection_name)
    """
    default_collection: str | None = None
    default_split = DEFAULT_SPLIT

    if isinstance(payload, dict):
        default_collection = payload.get("collection_name")
        if payload.get("default_split"):
            default_split = str(payload["default_split"]).strip().lower()
        raw_queries = payload.get("queries")
        if raw_queries is None:
            raise ValueError("Golden set object is missing the 'queries' key.")
    elif isinstance(payload, list):
        raw_queries = payload
    else:
        raise ValueError("Golden set must be a JSON object with 'queries', or a JSON list.")

    if default_split not in KNOWN_SPLITS:
        raise ValueError(
            f"Unknown default_split '{default_split}'. Expected one of {list(KNOWN_SPLITS)}."
        )

    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError("Golden set contains no queries.")

    queries: list[GoldenQuery] = []
    seen_ids: set[str] = set()

    for position, raw in enumerate(raw_queries, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Query #{position} is not an object.")

        query_id = str(raw.get("id") or f"Q{position}")
        question = raw.get("question")
        if not question or not str(question).strip():
            raise ValueError(f"Query '{query_id}' has an empty 'question'.")

        expected = raw.get("expected_chunk_ids")
        if expected is None:
            single = raw.get("expected_chunk_id")
            expected = [single] if single else []
        if isinstance(expected, str):
            expected = [expected]
        expected = [str(chunk_id) for chunk_id in expected if chunk_id]

        # Guard the undefined case at load time rather than scoring it 0.0 later.
        if not expected:
            raise ValueError(
                f"Query '{query_id}' has no expected chunk IDs. "
                "MRR is undefined for ungraded queries — remove it or grade it."
            )

        if query_id in seen_ids:
            raise ValueError(f"Duplicate query id '{query_id}' in golden set.")
        seen_ids.add(query_id)

        split = str(raw.get("split") or default_split).strip().lower()
        if split not in KNOWN_SPLITS:
            raise ValueError(
                f"Query '{query_id}' has unknown split '{split}'. "
                f"Expected one of {list(KNOWN_SPLITS)}."
            )

        sdk_version = raw.get("sdk_version")
        queries.append(
            GoldenQuery(
                id=query_id,
                question=str(question).strip(),
                expected_chunk_ids=tuple(expected),
                split=split,
                sdk_version=str(sdk_version) if sdk_version else None,
            )
        )

    return queries, default_collection


def load_golden_set(path: str | Path) -> tuple[list[GoldenQuery], str | None]:
    """Read and validate a golden-set JSON file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Golden set not found: {file_path}")
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Golden set '{file_path}' is not valid JSON: {exc}") from exc
    return parse_golden_set(payload)


def filter_by_split(golden_set: Sequence[GoldenQuery], split: str | None) -> list[GoldenQuery]:
    """
    Keep only the queries in the requested split. ``None`` keeps everything.

    Raises:
        ValueError: Unknown split name, or the split exists but is empty.
    """
    if not split:
        return list(golden_set)

    normalised = split.strip().lower()
    if normalised not in KNOWN_SPLITS:
        raise ValueError(f"Unknown split '{split}'. Expected one of {list(KNOWN_SPLITS)}.")

    subset = [query for query in golden_set if query.split == normalised]
    if not subset:
        raise ValueError(f"No queries in the '{normalised}' split.")
    return subset


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QueryEvaluation:
    """Per-query MRR breakdown — enough detail to debug a 0.0 without re-running."""

    id: str
    question: str
    split: str
    expected_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    first_relevant_rank: int | None
    reciprocal_rank: float


@dataclass(frozen=True)
class SplitScore:
    """MRR restricted to a single split."""

    split: str
    query_count: int
    mrr: float


@dataclass(frozen=True)
class MrrReport:
    collection_name: str
    top_k: int
    split: str | None
    query_count: int
    mrr: float
    split_scores: list[SplitScore] = field(default_factory=list)
    evaluations: list[QueryEvaluation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check_expected_ids_exist(
    collection_name: str,
    golden_set: Sequence[GoldenQuery],
) -> list[str]:
    """
    Confirm the golden set's expected chunk IDs actually exist in the collection.

    A golden set is authored against one specific corpus — its chunk IDs encode
    both the source filename and the chunk index, so pointing it at a different
    collection silently scores 0.0 on every query. That reads as "retrieval is
    broken" when it really means "wrong corpus", so it is worth failing loudly.

    Limitation: this only detects *absent* IDs. If the same document is
    re-chunked, the IDs still resolve but now point at different text, and the
    score degrades with no warning (e.g. 'sdk-v3-strategy-a' vs
    'sdk-v3-strategy-b' share IDs but not content). Catching that would require
    pinning expected content, not just IDs. Re-grade the golden set after any
    chunking change.

    Returns:
        Warning strings for a *partial* mismatch.

    Raises:
        ValueError: Not one expected chunk ID exists in the collection.
    """
    stored_ids = get_chunk_ids(collection_name)

    ungradable = [
        query.id
        for query in golden_set
        if not set(query.expected_chunk_ids) & stored_ids
    ]

    if len(ungradable) == len(golden_set):
        sample = sorted(golden_set[0].expected_chunk_ids)[:2]
        raise ValueError(
            f"None of the golden set's expected chunk IDs exist in collection "
            f"'{collection_name}' — every query would score 0.0. This golden set "
            f"was authored against a different corpus (it expects IDs like "
            f"{sample}). Evaluate the collection it was written for, or re-grade "
            f"the expected chunk IDs against this one."
        )

    if ungradable:
        return [
            f"{len(ungradable)} of {len(golden_set)} queries have no expected chunk ID "
            f"present in '{collection_name}' and can only score 0.0: "
            f"{', '.join(ungradable)}. Chunk IDs shift when a document is re-chunked."
        ]

    return []


def evaluate_mrr(
    collection_name: str,
    golden_set: Sequence[GoldenQuery],
    top_k: int | None = None,
    split: str | None = None,
) -> MrrReport:
    """
    Run every golden query through the live hybrid retriever and score MRR@k.

    Args:
        collection_name: Collection to search.
        golden_set: Graded queries from load_golden_set / parse_golden_set.
        top_k: Retrieval cutoff. Defaults to settings.top_k.
        split: Restrict to "dev" or "test". None evaluates everything and still
            reports each split separately.

    Returns:
        MrrReport with the aggregate MRR, a per-split breakdown, and a per-query
        breakdown.

    Raises:
        ValueError: Empty golden set, unknown/empty split, or missing collection.
    """
    if not golden_set:
        raise ValueError("Cannot compute MRR: the golden set is empty.")

    selected = filter_by_split(golden_set, split)
    effective_top_k = top_k if top_k and top_k > 0 else settings.top_k

    # Fail fast on a corpus mismatch rather than reporting a misleading 0.0.
    warnings = _check_expected_ids_exist(collection_name, selected)

    evaluations: list[QueryEvaluation] = []

    for query in selected:
        embedding = embed_query(query.question)
        where = {"sdk_version": query.sdk_version} if query.sdk_version else None

        retrieved = hybrid_query_chunks(
            collection_name=collection_name,
            query=query.question,
            query_embedding=embedding,
            top_k=effective_top_k,
            where=where,
        )
        retrieved_ids = [chunk["chunk_id"] for chunk in retrieved]

        rank = first_relevant_rank(retrieved_ids, query.expected_chunk_ids)
        evaluations.append(
            QueryEvaluation(
                id=query.id,
                question=query.question,
                split=query.split,
                expected_chunk_ids=list(query.expected_chunk_ids),
                retrieved_chunk_ids=retrieved_ids,
                first_relevant_rank=rank,
                reciprocal_rank=round(0.0 if rank is None else 1.0 / rank, 4),
            )
        )

    overall = mean_reciprocal_rank(item.reciprocal_rank for item in evaluations)

    split_scores: list[SplitScore] = []
    for name in KNOWN_SPLITS:
        subset = [item for item in evaluations if item.split == name]
        if subset:
            split_scores.append(
                SplitScore(
                    split=name,
                    query_count=len(subset),
                    mrr=round(mean_reciprocal_rank(item.reciprocal_rank for item in subset), 4),
                )
            )

    return MrrReport(
        collection_name=collection_name,
        top_k=effective_top_k,
        split=split.strip().lower() if split else None,
        query_count=len(evaluations),
        mrr=round(overall, 4),
        split_scores=split_scores,
        evaluations=evaluations,
        warnings=warnings,
    )
