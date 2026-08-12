"""
app/routes/upload.py
--------------------
POST /upload — Accept a PDF, chunk it, embed it, and store in ChromaDB.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import settings
from app.services.chunker import pdf_to_chunks
from app.services.embedder import embed_texts
from app.services.vector_store import add_chunks

router = APIRouter(prefix="/upload", tags=["Upload"])


# ─────────────────────────────────────────────────────────────────────────────
# Response schema
# ─────────────────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    status: str
    collection_name: str
    filename: str
    chunks_stored: int
    chunk_size: int
    chunk_overlap: int


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize_collection_name(name: str) -> str:
    """
    ChromaDB collection names must be 3-63 chars, alphanumeric + hyphens,
    cannot start/end with a hyphen, no consecutive hyphens.
    """
    # Replace non-alphanumeric (except hyphens) with hyphens
    sanitized = re.sub(r"[^a-zA-Z0-9-]", "-", name)
    # Collapse multiple hyphens
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")
    # Enforce length limits
    sanitized = sanitized[:63]
    if len(sanitized) < 3:
        sanitized = sanitized.ljust(3, "0")
    return sanitized.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=UploadResponse, summary="Upload and index a PDF document")
async def upload_document(
    file: UploadFile = File(..., description="PDF file to index"),
    collection_name: str = Form(
        default="",
        description="Optional collection name. Defaults to the sanitised filename stem.",
    ),
    chunk_size: int = Form(default=0, description="Override chunk size (0 = use .env default)"),
    chunk_overlap: int = Form(default=0, description="Override chunk overlap (0 = use .env default)"),
) -> UploadResponse:
    """
    Upload a PDF document and index it into ChromaDB.

    **Processing pipeline:**
    1. Validate the file is a PDF
    2. Extract text using PyMuPDF
    3. Split text into overlapping chunks (recursive character splitter)
    4. Generate embeddings (sentence-transformers, runs locally)
    5. Upsert into ChromaDB under the specified collection

    **Re-uploading the same document** is safe — existing chunks are overwritten.
    """
    # ── Validate file type ───────────────────────────────────────────────────
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # ── Resolve settings ─────────────────────────────────────────────────────
    effective_chunk_size = chunk_size if chunk_size > 0 else settings.chunk_size
    effective_chunk_overlap = chunk_overlap if chunk_overlap > 0 else settings.chunk_overlap

    if effective_chunk_overlap >= effective_chunk_size:
        raise HTTPException(
            status_code=400,
            detail=f"chunk_overlap ({effective_chunk_overlap}) must be less than chunk_size ({effective_chunk_size}).",
        )

    # ── Resolve collection name ───────────────────────────────────────────────
    stem = file.filename.rsplit(".", 1)[0]  # strip .pdf extension
    resolved_collection = _sanitize_collection_name(collection_name or stem)

    # ── Read file bytes ───────────────────────────────────────────────────────
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Chunk ────────────────────────────────────────────────────────────────
    try:
        chunks = pdf_to_chunks(
            pdf_bytes,
            chunk_size=effective_chunk_size,
            chunk_overlap=effective_chunk_overlap,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to process PDF: {exc}") from exc

    if not chunks:
        raise HTTPException(status_code=422, detail="No text could be extracted from the PDF.")

    # ── Embed ────────────────────────────────────────────────────────────────
    try:
        embeddings = embed_texts(chunks)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}") from exc

    # ── Store ────────────────────────────────────────────────────────────────
    try:
        stored = add_chunks(
            collection_name=resolved_collection,
            chunks=chunks,
            embeddings=embeddings,
            source_filename=file.filename,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector store error: {exc}") from exc

    return UploadResponse(
        status="ok",
        collection_name=resolved_collection,
        filename=file.filename,
        chunks_stored=stored,
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
    )
