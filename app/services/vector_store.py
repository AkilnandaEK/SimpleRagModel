"""
app/services/vector_store.py
-----------------------------
ChromaDB wrapper — handles all vector storage and retrieval.

Design decisions:
  - One ChromaDB *collection* per uploaded document.
    This lets you query specific documents without cross-contamination.
  - Embeddings are pre-computed by our sentence-transformer (embedder.py)
    and passed directly to Chroma — we do NOT use Chroma's built-in embedding
    functions so we keep full control over the embedding pipeline.
  - The client is a persistent client, so data survives server restarts.
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
    distance: float


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def add_chunks(
    collection_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
    source_filename: str,
) -> int:
    """
    Store text chunks and their embeddings in the given collection.

    If the collection already exists, new chunks are *upserted* (so re-uploading
    the same file is safe — it overwrites old data for that source).

    Args:
        collection_name:  Name of the ChromaDB collection (usually the filename stem).
        chunks:           List of text chunk strings.
        embeddings:       Corresponding embedding vectors (same length as chunks).
        source_filename:  Original filename stored as metadata on each chunk.

    Returns:
        Number of chunks stored.
    """
    client = _get_client()
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},  # use cosine similarity
    )

    ids = [f"{source_filename}__chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_filename, "chunk_index": i} for i in range(len(chunks))]

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )

    return len(chunks)


def query_chunks(
    collection_name: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """
    Find the most semantically similar chunks to the query embedding.

    Args:
        collection_name:  Collection to search in.
        query_embedding:  Embedding of the user's question.
        top_k:            Maximum number of results to return.

    Returns:
        List of RetrievedChunk dicts sorted by relevance (closest first).

    Raises:
        ValueError: If the collection does not exist.
    """
    client = _get_client()

    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        raise ValueError(f"Collection '{collection_name}' not found. Upload a document first.")

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "distances", "metadatas"],
    )

    retrieved: list[RetrievedChunk] = []
    if results["ids"] and results["ids"][0]:
        for chunk_id, doc, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["distances"][0],
        ):
            retrieved.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=doc,
                    distance=round(float(dist), 4),
                )
            )

    return retrieved


def list_collections() -> list[dict]:
    """
    Return metadata for all existing collections.

    Returns:
        List of dicts with keys: name, count.
    """
    client = _get_client()
    collections = client.list_collections()
    return [
        {"name": col.name, "count": col.count()}
        for col in collections
    ]


def delete_collection(collection_name: str) -> bool:
    """
    Delete a collection and all its stored chunks.

    Args:
        collection_name: Name of the collection to delete.

    Returns:
        True if deleted, False if it didn't exist.
    """
    client = _get_client()
    try:
        client.delete_collection(name=collection_name)
        return True
    except Exception:
        return False
