"""
app/routes/query.py
-------------------
POST /query                  — Answer a question using RAG + Gemini with citations, debug/eval metadata.
GET  /collections             — List all indexed collections.
DELETE /collections/{n}       — Remove a collection.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import google.generativeai as genai

from app.core.config import settings
from app.services.embedder import embed_query
from app.services.hybrid_retrieval import hybrid_query_chunks
from app.services.vector_store import delete_collection, list_collections

genai.configure(api_key=settings.gemini_api_key)

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
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse, summary="Ask a question about an indexed document")
async def query_document(body: QueryRequest) -> QueryResponse:
    """
    RAG query pipeline with optional debug/evaluation details and metadata filtering.
    """
    effective_top_k = body.top_k if body.top_k > 0 else settings.top_k

    try:
        q_embedding = embed_query(body.question)
    except Exception as exc:
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {exc}") from exc

    if not retrieved:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found in collection '{body.collection_name}'. Is the document uploaded?",
        )

    prompt, context_block = _build_prompt(body.question, retrieved)

    try:
        model = genai.GenerativeModel(settings.gemini_model)
        response = model.generate_content(prompt)
        answer = response.text.strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}") from exc

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
            llm_prompt=prompt,
            llm_response=answer,
            answer=answer,
            response_status=response_status,
            citations=citations,
        )

    return QueryResponse(
        answer=answer,
        collection_name=body.collection_name,
        question=body.question,
        sources=sources,
        chunks_used=len(sources),
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
