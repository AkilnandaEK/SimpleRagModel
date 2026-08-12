"""
app/routes/query.py
-------------------
POST /query      — Answer a question using RAG + Gemini.
GET  /collections — List all indexed collections.
DELETE /collections/{name} — Remove a collection.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import google.generativeai as genai

from app.core.config import settings
from app.services.embedder import embed_query
from app.services.vector_store import delete_collection, list_collections, query_chunks

# Configure Gemini once at module load
genai.configure(api_key=settings.gemini_api_key)

router = APIRouter(tags=["Query & Collections"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The question to ask about the document.")
    collection_name: str = Field(..., min_length=1, description="Which collection (document) to search.")
    top_k: int = Field(default=0, ge=0, description="Number of chunks to retrieve (0 = use .env default).")


class SourceChunk(BaseModel):
    chunk_id: str
    text: str
    distance: float


class QueryResponse(BaseModel):
    answer: str
    collection_name: str
    question: str
    sources: list[SourceChunk]
    chunks_used: int


class CollectionInfo(BaseModel):
    name: str
    count: int


class DeleteResponse(BaseModel):
    status: str
    collection_name: str


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(question: str, context_chunks: list[str]) -> str:
    """
    Construct the context-stuffed prompt sent to Gemini.

    The prompt instructs Gemini to:
    - Answer ONLY from the provided context
    - Cite the information rather than hallucinating
    - Say "I don't know" if the context is insufficient
    """
    context_block = "\n\n---\n\n".join(
        f"[Chunk {i + 1}]:\n{chunk}" for i, chunk in enumerate(context_chunks)
    )

    return f"""You are a precise, helpful assistant that answers questions strictly based on the provided document context.

## Instructions
- Answer the question using ONLY the information found in the context below.
- If the context does not contain enough information to answer the question, respond with:
  "I don't have enough information in the provided document to answer that question."
- Do NOT fabricate facts or use outside knowledge.
- Be concise but complete. Use bullet points or numbered lists when appropriate.
- If you quote directly from the context, use quotation marks.

## Document Context
{context_block}

## Question
{question}

## Answer
"""


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse, summary="Ask a question about an indexed document")
async def query_document(body: QueryRequest) -> QueryResponse:
    """
    RAG query pipeline:
    1. Embed the user's question (sentence-transformers)
    2. Retrieve top-K similar chunks from ChromaDB
    3. Build a context-stuffed prompt
    4. Send to Gemini and return the answer
    """
    effective_top_k = body.top_k if body.top_k > 0 else settings.top_k

    # ── Embed question ───────────────────────────────────────────────────────
    try:
        q_embedding = embed_query(body.question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}") from exc

    # ── Retrieve chunks ───────────────────────────────────────────────────────
    try:
        retrieved = query_chunks(
            collection_name=body.collection_name,
            query_embedding=q_embedding,
            top_k=effective_top_k,
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

    # ── Build prompt ─────────────────────────────────────────────────────────
    context_texts = [chunk["text"] for chunk in retrieved]
    prompt = _build_prompt(body.question, context_texts)

    # ── Call Gemini ───────────────────────────────────────────────────────────
    try:
        model = genai.GenerativeModel(settings.gemini_model)
        response = model.generate_content(prompt)
        answer = response.text.strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}") from exc

    # ── Format sources ────────────────────────────────────────────────────────
    sources = [
        SourceChunk(
            chunk_id=chunk["chunk_id"],
            text=chunk["text"],
            distance=chunk["distance"],
        )
        for chunk in retrieved
    ]

    return QueryResponse(
        answer=answer,
        collection_name=body.collection_name,
        question=body.question,
        sources=sources,
        chunks_used=len(sources),
    )


@router.get("/collections", response_model=list[CollectionInfo], summary="List all indexed document collections")
async def get_collections() -> list[CollectionInfo]:
    """Return all collections currently stored in ChromaDB with their chunk counts."""
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
    """
    Permanently delete a collection and all its stored chunks from ChromaDB.

    This is irreversible — you will need to re-upload the document to query it again.
    """
    deleted = delete_collection(collection_name)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Collection '{collection_name}' not found.",
        )
    return DeleteResponse(status="deleted", collection_name=collection_name)
