"""Production BM25 + reciprocal-rank-fusion retrieval over Chroma chunks."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.services.vector_store import RetrievedChunk, _get_client, query_chunks

RRF_K = 60
_BM25_DOCUMENTS: dict[str, list["_Bm25Document"]] = {}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_.]+", text.lower())


@dataclass
class _Bm25Document:
    chunk_id: str
    text: str
    metadata: dict
    terms: Counter[str]
    length: int


def refresh_bm25_index(collection_name: str) -> None:
    """Build the in-process BM25 index from the collection's stored chunk text."""
    try:
        collection = _get_client().get_collection(name=collection_name)
    except Exception as exc:
        raise ValueError(f"Collection '{collection_name}' not found. Upload a document first.") from exc
    result = collection.get(include=["documents", "metadatas"])
    _BM25_DOCUMENTS[collection_name] = [
        _Bm25Document(chunk_id=cid, text=text, metadata=meta or {}, terms=Counter(_tokenize(text)), length=len(_tokenize(text)))
        for cid, text, meta in zip(result["ids"], result["documents"], result.get("metadatas") or [])
    ]


def _bm25_rank(collection_name: str, query: str, top_n: int, where: dict | None) -> list[_Bm25Document]:
    """Rank the same documents stored in ChromaDB with BM25."""
    if collection_name not in _BM25_DOCUMENTS:
        refresh_bm25_index(collection_name)
    documents = _BM25_DOCUMENTS[collection_name]
    if where:
        documents = [document for document in documents if all(document.metadata.get(key) == value for key, value in where.items())]
    if not documents:
        return []
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(document.terms.keys())
    avg_length = sum(document.length for document in documents) / len(documents)
    query_terms = _tokenize(query)
    k1, b = 1.5, 0.75

    def score(document: _Bm25Document) -> float:
        total = 0.0
        for term in query_terms:
            frequency = document.terms.get(term, 0)
            if frequency:
                idf = math.log((len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5) + 1)
                total += idf * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * document.length / avg_length))
        return total
    return sorted(documents, key=score, reverse=True)[:top_n]


def _rrf(vector_ids: list[str], bm25_ids: list[str]) -> list[str]:
    """Fuse ranked lists by rank position only; raw retrieval scores are never compared."""
    scores: dict[str, float] = {}
    for ranking in (vector_ids, bm25_ids):
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)


def hybrid_query_chunks(collection_name: str, query: str, query_embedding: list[float], top_k: int = 5, where: dict | None = None) -> list[RetrievedChunk]:
    """Return final Top-K chunks from independent vector and BM25 rankings fused with RRF."""
    candidate_count = max(top_k * 5, 25)
    vector_chunks = query_chunks(collection_name, query_embedding, top_k=candidate_count, where=where)
    bm25_chunks = _bm25_rank(collection_name, query, candidate_count, where)
    vector_by_id = {chunk["chunk_id"]: chunk for chunk in vector_chunks}
    bm25_by_id = {chunk.chunk_id: chunk for chunk in bm25_chunks}
    fused_ids = _rrf(list(vector_by_id), list(bm25_by_id))[:top_k]
    return [
        vector_by_id[chunk_id] if chunk_id in vector_by_id else RetrievedChunk(
            chunk_id=bm25_by_id[chunk_id].chunk_id,
            text=bm25_by_id[chunk_id].text,
            distance=None,
            metadata=bm25_by_id[chunk_id].metadata,
        )
        for chunk_id in fused_ids
    ]
