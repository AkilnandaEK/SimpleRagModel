"""
app/routes/query.py
-------------------
POST /query                  — Answer a question using RAG + LLM with citations, debug/eval metadata.
GET  /collections             — List all indexed collections.
DELETE /collections/{n}       — Remove a collection.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.embedder import embed_query
from app.services.hybrid_retrieval import hybrid_query_chunks
from app.services.llm_provider import generate_answer
from app.services.tracing import PROMPT_VERSION, new_trace_id, save_trace, utc_timestamp
from app.services.vector_store import delete_collection, list_collections

router = APIRouter(tags=["Query & Collections"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The question to ask about the document.")
    collection_name: str = Field(..., min_length=1, description="Which collection (document) to search.")
    top_k: int = Field(default=0, ge=0, description="Number of chunks to retrieve (0 = default).")
    sdk_version: str | None = Field(default=None, description="Optional metadata filter for sdk_version (e.g. 'v3').")
    debug: bool = Field(default=False, description="Whether to return complete evaluation/debug details.")


class SourceChunk(BaseModel):
    chunk_id: str
    text: str
    distance: float | None = None
    source_file: str | None = None
    page_id: str | None = None
    anchor: str | None = None
    citation: str | None = None
    metadata: dict[str, Any] | None = None


class CitationDetail(BaseModel):
    chunk_id: str
    source_file: str | None = None
    page_id: str | None = None
    anchor: str | None = None
    section: str | None = None


class EvaluationChunk(BaseModel):
    rank: int
    chunk_id: str
    text: str
    distance: float | None = None
    similarity_score: float | None = None
    source_file: str | None = None
    page_id: str | None = None
    page: str | None = None
    sdk_version: str | None = None
    page_type: str | None = None
    section: str | None = None
    parent_section: str | None = None
    anchor: str | None = None
    chunk_index: int | None = None
    metadata: dict[str, Any]


class EvaluationDetails(BaseModel):
    enabled: bool = True
    query: str
    collection_name: str
    chunking_strategy: str
    sdk_version: str | None = None
    top_k: int
    metadata_filter: dict[str, Any] | None = None
    retrieved_chunks: list[EvaluationChunk]
    context: str
    llm_prompt: str
    llm_response: str
    answer: str
    response_status: str  # "answered" or "refused"
    citations: list[CitationDetail]


class QueryResponse(BaseModel):
    answer: str
    collection_name: str
    question: str
    sources: list[SourceChunk]
    chunks_used: int
    trace_id: str | None = None
    evaluation: EvaluationDetails | None = None


class CollectionInfo(BaseModel):
    name: str
    count: int


class DeleteResponse(BaseModel):
    status: str
    collection_name: str


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(question: str, context_chunks: list[dict]) -> tuple[str, str]:
    """
    Construct context-stuffed prompt sent to Gemini with explicit citation hints.
    Returns tuple of (full_prompt_string, context_block_string).
    """
    formatted_chunks = []
    for i, c in enumerate(context_chunks, start=1):
        meta = c.get("metadata", {})
        chunk_id = c.get("chunk_id", f"chunk_{i}")
        page = meta.get("page_id") or meta.get("page") or "1"
        anchor = meta.get("anchor") or "#section"
        source = meta.get("source_file") or meta.get("source") or "doc"

        header = f"[Chunk {i} | ID: {chunk_id} | Source: {source} | Page: {page} | Anchor: {anchor}]"
        formatted_chunks.append(f"{header}\n{c.get('text', '')}")

    context_block = "\n\n---\n\n".join(formatted_chunks)

    prompt = f"""You are a precise, helpful assistant that answers questions strictly based on the provided document context.

## Instructions
- Answer the question using ONLY the information found in the context below.
- If the context does not contain enough information to answer the question, respond with EXACTLY:
  "I don't have enough information in the provided document to answer that question."
- Do NOT fabricate facts or use outside knowledge.
- Be concise but complete. Use bullet points or numbered lists when appropriate.
- Include citations referencing the chunk ID, Page, and Anchor when citing facts.

## Document Context
{context_block}

## Question
{question}

## Answer
"""
    return prompt, context_block


# ─────────────────────────────────────────────────────────────────────────────
# Trace helpers
# ─────────────────────────────────────────────────────────────────────────────

def _save_error_trace(
    trace_id: str,
    question: str,
    collection_name: str,
    top_k: int,
    error: Exception,
    status_code: int,
    retrieved_chunks_info: list[dict] | None = None,
    prompt: str | None = None,
) -> None:
    """Persist a partial trace when the request fails before completion."""
    trace = {
        "trace_id": trace_id,
        "timestamp": utc_timestamp(),
        "question": question,
        "prompt_version": PROMPT_VERSION,
        "provider": settings.llm_provider,
        "model": settings.active_model,
        "model_parameters": {},
        "collection_name": collection_name,
        "top_k": top_k,
        "retrieved_chunks": retrieved_chunks_info or [],
        "prompt": prompt,
        "raw_output": None,
        "answer": None,
        "response_status": None,
        "status": "error",
        "error": {
            "type": error.__class__.__name__,
            "status_code": status_code,
            "detail": str(error),
        },
    }
    save_trace(trace)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse, summary="Ask a question about an indexed document")
async def query_document(body: QueryRequest) -> QueryResponse:
    """
    RAG query pipeline with optional debug/evaluation details and metadata filtering.
    """
    trace_id = new_trace_id()
    effective_top_k = body.top_k if body.top_k > 0 else settings.top_k

    # Accumulators for trace data — updated as the pipeline progresses so that
    # a failure can still persist a useful partial trace.
    retrieved_chunks_info: list[dict] = []
    prompt_sent: str | None = None

    try:
        q_embedding = embed_query(body.question)
    except Exception as exc:
        _save_error_trace(trace_id, body.question, body.collection_name, effective_top_k, exc, 500)
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}") from exc

    where_filter = None
    if body.sdk_version:
        where_filter = {"sdk_version": body.sdk_version}

    try:
        retrieved = hybrid_query_chunks(
            collection_name=body.collection_name,
            query=body.question,
            query_embedding=q_embedding,
            top_k=effective_top_k,
            where=where_filter,
        )
    except ValueError as exc:
        _save_error_trace(trace_id, body.question, body.collection_name, effective_top_k, exc, 404)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _save_error_trace(trace_id, body.question, body.collection_name, effective_top_k, exc, 500)
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

    if not retrieved:
        exc = ValueError(
            f"No chunks found in collection '{body.collection_name}'. Is the document uploaded?"
        )
        _save_error_trace(trace_id, body.question, body.collection_name, effective_top_k, exc, 404)
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found in collection '{body.collection_name}'. Is the document uploaded?",
        )

    for rank, chunk in enumerate(retrieved, start=1):
        retrieved_chunks_info.append(
            {
                "chunk_id": chunk["chunk_id"],
                "rank": rank,
                "text": chunk.get("text"),
                "distance": chunk.get("distance"),
                "source_file": chunk.get("metadata", {}).get("source_file"),
            }
        )

    prompt_sent, context_block = _build_prompt(body.question, retrieved)

    try:
        llm_result = generate_answer(prompt_sent)
        raw_output = llm_result.raw_text
        answer = raw_output.strip()
    except Exception as exc:
        _save_error_trace(
            trace_id, body.question, body.collection_name, effective_top_k,
            exc, 502, retrieved_chunks_info, prompt_sent,
        )
        raise HTTPException(status_code=502, detail=f"LLM API error: {exc}") from exc

    model_parameters = llm_result.model_parameters

    # Determine refusal status
    refusal_trigger = "I don't have enough information in the provided document"
    response_status = "refused" if refusal_trigger.lower() in answer.lower() else "answered"

    sources: list[SourceChunk] = []
    eval_chunks: list[EvaluationChunk] = []
    citations: list[CitationDetail] = []

    for rank, chunk in enumerate(retrieved, start=1):
        meta = chunk.get("metadata", {})
        src_file = meta.get("source_file") or meta.get("source") or "document"
        page_id = str(meta.get("page_id") or meta.get("page") or "1")
        anchor = str(meta.get("anchor") or "#section")

        citation_str = f"{chunk['chunk_id']} | Page: {page_id} | Anchor: {anchor}"

        sources.append(
            SourceChunk(
                chunk_id=chunk["chunk_id"],
                text=chunk["text"],
                distance=chunk["distance"],
                source_file=src_file,
                page_id=page_id,
                anchor=anchor,
                citation=citation_str,
                metadata=meta,
            )
        )

        sim_score = max(0.0, round(1.0 - (chunk["distance"] / 2.0), 4)) if chunk["distance"] is not None else None

        eval_chunks.append(
            EvaluationChunk(
                rank=rank,
                chunk_id=chunk["chunk_id"],
                text=chunk["text"],
                distance=chunk["distance"],
                similarity_score=sim_score,
                source_file=src_file,
                page_id=page_id,
                page=str(meta.get("page")) if meta.get("page") is not None else page_id,
                sdk_version=meta.get("sdk_version"),
                page_type=meta.get("page_type"),
                section=meta.get("section"),
                parent_section=meta.get("parent_section"),
                anchor=anchor,
                chunk_index=meta.get("chunk_index"),
                metadata=meta,
            )
        )

        citations.append(
            CitationDetail(
                chunk_id=chunk["chunk_id"],
                source_file=src_file,
                page_id=page_id,
                anchor=anchor,
                section=meta.get("section"),
            )
        )

    eval_details = None
    if body.debug:
        eval_details = EvaluationDetails(
            enabled=True,
            query=body.question,
            collection_name=body.collection_name,
            chunking_strategy="context-aware",
            sdk_version=body.sdk_version,
            top_k=effective_top_k,
            metadata_filter=where_filter,
            retrieved_chunks=eval_chunks,
            context=context_block,
            llm_prompt=prompt_sent,
            llm_response=answer,
            answer=answer,
            response_status=response_status,
            citations=citations,
        )

    # ── Persist trace ──────────────────────────────────────────────────────────
    trace = {
        "trace_id": trace_id,
        "timestamp": utc_timestamp(),
        "question": body.question,
        "prompt_version": PROMPT_VERSION,
        "provider": llm_result.provider,
        "model": llm_result.model,
        "model_parameters": model_parameters,
        "collection_name": body.collection_name,
        "top_k": effective_top_k,
        "retrieved_chunks": retrieved_chunks_info,
        "prompt": prompt_sent,
        "raw_output": raw_output,
        "answer": answer,
        "response_status": response_status,
        "status": "success",
    }
    save_trace(trace)

    return QueryResponse(
        answer=answer,
        collection_name=body.collection_name,
        question=body.question,
        sources=sources,
        chunks_used=len(sources),
        trace_id=trace_id,
        evaluation=eval_details,
    )


@router.get("/collections", response_model=list[CollectionInfo], summary="List all indexed document collections")
async def get_collections() -> list[CollectionInfo]:
    try:
        cols = list_collections()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not list collections: {exc}") from exc
    return [CollectionInfo(name=c["name"], count=c["count"]) for c in cols]


@router.delete(
    "/collections/{collection_name}",
    response_model=DeleteResponse,
    summary="Delete a document collection",
)
async def remove_collection(collection_name: str) -> DeleteResponse:
    deleted = delete_collection(collection_name)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Collection '{collection_name}' not found.",
        )
    return DeleteResponse(status="deleted", collection_name=collection_name)
