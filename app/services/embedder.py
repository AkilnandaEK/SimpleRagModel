"""
app/services/embedder.py
------------------------
Thin wrapper around sentence-transformers for generating embeddings.

The model is loaded once at module import time (lazy singleton pattern) so
there's no repeated disk I/O across requests.

Model: all-MiniLM-L6-v2
  - 384-dimensional dense vectors
  - ~22 MB download on first run
  - Extremely fast on CPU
  - Consistently ranks well on semantic similarity benchmarks
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Singleton model loader
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """
    Load the sentence-transformer model exactly once per process.
    The model is cached in memory — subsequent calls return the same instance.
    """
    print(f"[embedder] Loading model '{settings.embedding_model}' …")
    model = SentenceTransformer(settings.embedding_model)
    print(f"[embedder] Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")
    return model


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Convert a list of strings into their embedding vectors.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of float vectors (one per input text).
    """
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    """
    Convenience wrapper for embedding a single query string.

    Args:
        query: The question or search string.

    Returns:
        A single float vector.
    """
    return embed_texts([query])[0]
