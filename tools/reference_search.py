"""
tools/reference_search.py
-------------------------------
Tool 1: Search the reference corpus for relevant information.
Uses the existing Week 3 RAG retrieval pipeline (ChromaDB + hybrid retrieval).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.services.embedder import embed_query
from app.services.hybrid_retrieval import hybrid_query_chunks


# ── Input Schema ─────────────────────────────────────────────────────────────

class ReferenceSearchInput(BaseModel):
    query: str = Field(..., min_length=1, description="The search query to find relevant reference material.")
    target_files: list[str] | None = Field(default=None, description="Optional list of target files to filter search within.")
    version: str | None = Field(default=None, description="Optional version filter (e.g., 'v3', '2.x').")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of results to return.")


# ── Output Schema ────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    chunk_id: str
    text: str
    distance: float | None = None
    source_file: str | None = None
    relevance: float | None = None
    metadata: dict[str, Any] = {}


class ReferenceSearchOutput(BaseModel):
    query: str
    results: list[SearchResult]
    result_count: int
    collection_searched: str
    status: str  # "found" or "not_found"


# ── Tool Implementation ──────────────────────────────────────────────────────

def reference_search(
    input_data: ReferenceSearchInput,
    collection_name: str = "sdk-v3-strategy-b",
) -> ReferenceSearchOutput:
    """
    Search the reference corpus for chunks matching the query.
    Returns structured search results with relevance scores.
    """
    try:
        query_embedding = embed_query(input_data.query)
    except Exception as exc:
        return ReferenceSearchOutput(
            query=input_data.query,
            results=[],
            result_count=0,
            collection_searched=collection_name,
            status=f"error: embedding failed: {exc}",
        )

    where_filter = None
    if input_data.version:
        where_filter = {"sdk_version": input_data.version}

    try:
        retrieved = hybrid_query_chunks(
            collection_name=collection_name,
            query=input_data.query,
            query_embedding=query_embedding,
            top_k=input_data.top_k,
            where=where_filter,
        )
    except Exception as exc:
        return ReferenceSearchOutput(
            query=input_data.query,
            results=[],
            result_count=0,
            collection_searched=collection_name,
            status=f"error: retrieval failed: {exc}",
        )

    results = []
    for chunk in retrieved:
        meta = chunk.get("metadata", {})
        distance = chunk.get("distance")
        relevance = max(0.0, round(1.0 - (distance / 2.0), 4)) if distance is not None else None

        src_file = meta.get("source_file") or meta.get("source") or ""

        if input_data.target_files and src_file not in input_data.target_files:
            continue

        results.append(SearchResult(
            chunk_id=chunk["chunk_id"],
            text=chunk["text"],
            distance=distance,
            source_file=src_file,
            relevance=relevance,
            metadata=meta,
        ))

    status = "found" if results else "not_found"
    return ReferenceSearchOutput(
        query=input_data.query,
        results=results,
        result_count=len(results),
        collection_searched=collection_name,
        status=status,
    )