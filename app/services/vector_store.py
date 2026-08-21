"""
app/services/vector_store.py
-----------------------------
ChromaDB wrapper — handles all vector storage, metadata filtering, and retrieval.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Singleton ChromaDB client
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_client() -> chromadb.ClientAPI:
    """Return (and cache) the persistent ChromaDB client."""
    print(f"[vector_store] Connecting to ChromaDB at '{settings.chroma_persist_dir}' …")
    client = chromadb.PersistentClient(
        path=settings.chroma_persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Type hints
# ─────────────────────────────────────────────────────────────────────────────

class RetrievedChunk(TypedDict):
    chunk_id: str
    text: str
    distance: float | None
    metadata: dict


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def add_chunks(
    collection_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    source_filename: str,
    metadatas: list[dict] | None = None,
) -> int:
    """
    Store text chunks and their embeddings in the given collection.
    Overwrites/upserts existing chunks for safe re-ingestion.
    """
    client = _get_client()
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    ids = [f"{source_filename}__chunk_{i}" for i in range(len(chunks))]

    final_metadatas: list[dict] = []
    for i, chunk in enumerate(chunks):
        meta: dict = {}
        if metadatas and i < len(metadatas) and isinstance(metadatas[i], dict):
            meta = dict(metadatas[i])
        elif hasattr(chunk, "metadata") and isinstance(getattr(chunk, "metadata"), dict):
            meta = dict(getattr(chunk, "metadata"))

        if "source" not in meta:
            meta["source"] = source_filename
        if "source_file" not in meta:
            meta["source_file"] = source_filename
        meta["chunk_index"] = i
        final_metadatas.append(meta)

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=[str(c) for c in chunks],
        metadatas=final_metadatas,
    )

    return len(chunks)


def query_chunks(
    collection_name: str,
    query_embedding: list[float],
    top_k: int = 5,
    where: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Find the most semantically similar chunks with optional metadata filtering.

    Args:
        collection_name: Collection to search in.
        query_embedding: Embedding vector of the user's question.
        top_k: Maximum number of results to return.
        where: Optional ChromaDB metadata filter dictionary e.g. {"sdk_version": "v3"}.

    Returns:
        List of RetrievedChunk dicts with metadata attached.
    """
    client = _get_client()

    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        raise ValueError(f"Collection '{collection_name}' not found. Upload a document first.")

    query_args = {
        "query_embeddings": [query_embedding],
        "n_results": min(top_k, collection.count()),
        "include": ["documents", "distances", "metadatas"],
    }
    if where:
        query_args["where"] = where

    results = collection.query(**query_args)

    retrieved: list[RetrievedChunk] = []
    if results["ids"] and results["ids"][0]:
        for chunk_id, doc, dist, meta in zip(
            results["ids"][0],
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0] if results.get("metadatas") else [{}] * len(results["ids"][0]),
        ):
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=doc,
                    distance=round(float(dist), 4),
                    metadata=meta or {},
                )
            )

    return retrieved


def get_chunk_ids(collection_name: str) -> set[str]:
    """
    Return every chunk ID stored in the collection.

    Used by the MRR evaluator to tell "the retriever ranked badly" (a real 0.0)
    apart from "these expected chunk IDs don't exist here" (a config mistake).
    """
    client = _get_client()

    try:
        collection = client.get_collection(name=collection_name)
    except Exception as exc:
        raise ValueError(
            f"Collection '{collection_name}' not found. Upload a document first."
        ) from exc

    return set(collection.get(include=[])["ids"])


def list_collections() -> list[dict]:
    """Return metadata for all existing collections."""
    client = _get_client()
    collections = client.list_collections()
    return [
        {"name": col.name, "count": col.count()}
        for col in collections
    ]


def delete_collection(collection_name: str) -> bool:
    """Delete a collection and all its stored chunks."""
    client = _get_client()
    try:
        client.delete_collection(name=collection_name)
        return True
    except Exception:
        return False
