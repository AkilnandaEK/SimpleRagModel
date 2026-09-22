"""
tools/chunk_retrieval.py
-------------------------------
Tool 2: Retrieve a specific reference chunk/document section after search identifies a source.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.vector_store import query_chunks, _get_client


# ── Input Schema ─────────────────────────────────────────────────────────────

class ChunkRetrievalInput(BaseModel):
    chunk_id: str = Field(..., min_length=1, description="The chunk ID to retrieve.")
    collection_name: str = Field(default="sdk-v3-strategy-b", description="Collection to search in.")
    include_context: bool = Field(default=True, description="Whether to include surrounding chunks for context.")


# ── Output Schema ────────────────────────────────────────────────────────────

class ChunkContent(BaseModel):
    chunk_id: str
    text: str
    source_file: str | None = None
    page_id: str | None = None
    section: str | None = None
    metadata: dict[str, Any] = {}


class ChunkRetrievalOutput(BaseModel):
    requested_chunk_id: str
    chunk: ChunkContent | None = None
    context_chunks: list[ChunkContent] = []
    status: str  # "found", "not_found", or "error"


# ── Tool Implementation ──────────────────────────────────────────────────────

def chunk_retrieval(input_data: ChunkRetrievalInput) -> ChunkRetrievalOutput:
    """
    Retrieve a specific chunk by ID from the vector store.
    Optionally includes context chunks from the same source document.
    """
    try:
        client = _get_client()
        collection = client.get_collection(name=input_data.collection_name)
    except Exception as exc:
        return ChunkRetrievalOutput(
            requested_chunk_id=input_data.chunk_id,
            chunk=None,
            context_chunks=[],
            status=f"error: collection not found: {exc}",
        )

    try:
        result = collection.get(
            ids=[input_data.chunk_id],
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        return ChunkRetrievalOutput(
            requested_chunk_id=input_data.chunk_id,
            chunk=None,
            context_chunks=[],
            status=f"error: retrieval failed: {exc}",
        )

    if not result["ids"] or not result["ids"][0]:
        return ChunkRetrievalOutput(
            requested_chunk_id=input_data.chunk_id,
            chunk=None,
            context_chunks=[],
            status="not_found",
        )

    doc = result["documents"][0]
    meta = result["metadatas"][0] if result.get("metadatas") else {}

    chunk = ChunkContent(
        chunk_id=input_data.chunk_id,
        text=doc,
        source_file=meta.get("source_file") or meta.get("source"),
        page_id=str(meta.get("page_id") or meta.get("page") or ""),
        section=meta.get("section"),
        metadata=meta,
    )

    context_chunks = []
    if input_data.include_context:
        source_file = meta.get("source_file") or meta.get("source")
        if source_file:
            try:
                all_docs = collection.get(
                    include=["documents", "metadatas"],
                )
                for cid, cdoc, cmeta in zip(
                    all_docs["ids"], all_docs["documents"], all_docs.get("metadatas") or []
                ):
                    if cid == input_data.chunk_id:
                        continue
                    csrc = (cmeta or {}).get("source_file") or (cmeta or {}).get("source")
                    if csrc == source_file:
                        context_chunks.append(ChunkContent(
                            chunk_id=cid,
                            text=cdoc,
                            source_file=csrc,
                            page_id=str((cmeta or {}).get("page_id") or (cmeta or {}).get("page") or ""),
                            section=(cmeta or {}).get("section"),
                            metadata=cmeta or {},
                        ))
            except Exception:
                pass

    return ChunkRetrievalOutput(
        requested_chunk_id=input_data.chunk_id,
        chunk=chunk,
        context_chunks=context_chunks[:5],
        status="found",
    )