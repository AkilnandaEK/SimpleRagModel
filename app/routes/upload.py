"""
app/routes/upload.py
--------------------
POST /upload — Accept PDF or Markdown documents, chunk them with the
context-aware chunker, embed, and store them in ChromaDB.
"""

from __future__ import annotations

import re
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import settings
from app.services.chunker import pdf_to_chunks, _split_large_text, ChunkText
from app.services.structure_chunker import markdown_to_structure_chunks
from app.services.embedder import embed_texts
from app.services.hybrid_retrieval import refresh_bm25_index
from app.services.vector_store import add_chunks

router = APIRouter(prefix="/upload", tags=["Upload"])


class UploadResponse(BaseModel):
    status: str
    collection_name: str
    filename: str
    chunks_stored: int
    chunking_method: str
    chunk_size: int
    chunk_overlap: int


def _sanitize_collection_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9-]", "-", name)
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")
    sanitized = sanitized[:63]
    if len(sanitized) < 3:
        sanitized = sanitized.ljust(3, "0")
    return sanitized.lower()


@router.post("", response_model=UploadResponse, summary="Upload and index a document")
async def upload_document(
    file: UploadFile = File(..., description="PDF or Markdown file to index"),
    collection_name: str = Form(
        default="",
        description="Optional collection name. Defaults to sanitised filename stem.",
    ),
    sdk_version: str = Form(default="v3", description="SDK version metadata (v2, v3, etc.)"),
    page_type: str = Form(default="reference", description="Page type metadata (reference, guide, etc.)"),
    chunk_size: int = Form(default=0, description="Override chunk size"),
    chunk_overlap: int = Form(default=0, description="Override chunk overlap"),
) -> UploadResponse:
    filename = file.filename or "document.txt"
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext not in {"pdf", "md", "markdown", "txt"}:
        raise HTTPException(status_code=400, detail="Only PDF and Markdown/txt files are supported.")

    effective_chunk_size = chunk_size if chunk_size > 0 else settings.chunk_size
    effective_chunk_overlap = chunk_overlap if chunk_overlap > 0 else settings.chunk_overlap

    if effective_chunk_overlap >= effective_chunk_size:
        raise HTTPException(
            status_code=400,
            detail=f"chunk_overlap ({effective_chunk_overlap}) must be less than chunk_size ({effective_chunk_size}).",
        )

    stem = filename.rsplit(".", 1)[0]
    resolved_collection = _sanitize_collection_name(collection_name or stem)

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    page_id = stem

    try:
        if ext in {"md", "markdown"}:
            text_content = content_bytes.decode("utf-8", errors="ignore")
            chunks = markdown_to_structure_chunks(
                content=text_content,
                default_metadata={
                    "source_file": filename,
                    "page_id": page_id,
                    "sdk_version": sdk_version,
                    "page_type": page_type,
                },
                chunk_size=effective_chunk_size,
                chunk_overlap=effective_chunk_overlap,
            )
        else:
            chunks = pdf_to_chunks(
                content_bytes,
                chunk_size=effective_chunk_size,
                chunk_overlap=effective_chunk_overlap,
            )
            # Attach default metadata to PDF chunks if not set
            for c in chunks:
                if not getattr(c, "metadata", None):
                    c.metadata = {}
                c.metadata.setdefault("source_file", filename)
                c.metadata.setdefault("page_id", page_id)
                c.metadata.setdefault("sdk_version", sdk_version)
                c.metadata.setdefault("page_type", page_type)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to process document: {exc}") from exc

    if not chunks:
        raise HTTPException(status_code=422, detail="No text could be extracted from document.")

    chunk_texts = [str(c) for c in chunks]
    chunk_metadatas = [getattr(c, "metadata", {}) for c in chunks]

    try:
        embeddings = embed_texts(chunk_texts)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}") from exc

    try:
        stored = add_chunks(
            collection_name=resolved_collection,
            chunks=chunk_texts,
            embeddings=embeddings,
            source_filename=filename,
            metadatas=chunk_metadatas,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector store error: {exc}") from exc

    try:
        refresh_bm25_index(resolved_collection)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"BM25 indexing failed: {exc}") from exc

    return UploadResponse(
        status="ok",
        collection_name=resolved_collection,
        filename=filename,
        chunks_stored=stored,
        chunking_method="context-aware",
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
    )
