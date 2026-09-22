"""
tools/corpus_facts.py
---------------------
Ground truth about what the indexed corpus actually contains.

Both argument *validation* (Week 8 metrics) and argument *enforcement* (the
Week 8 mitigation) need the same answer to one question: which argument values
will the retrieval tool actually accept? Deriving that from the live collection
rather than hardcoding it means the checks cannot drift away from the index.

Lives under ``tools/`` because it describes the tool surface — this keeps the
agent from having to import anything out of ``eval/``.
"""

from __future__ import annotations

_CACHE: dict[str, tuple[frozenset[str], frozenset[str]]] = {}


def load_corpus_facts(collection_name: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(chunk_ids, accepted_version_values)`` for a collection.

    ``reference_search`` filters on the ``sdk_version`` metadata field, so the
    only ``version`` arguments that can ever match are the distinct values that
    field holds. A plausible-looking argument such as ``version="2025-06-01"``
    names a real API release but matches nothing — and the filter fails
    *silently*, returning zero results rather than an error.

    Cached per collection; the corpus is static for the life of an eval run.
    On any failure both sets come back empty, and callers are expected to skip
    the corresponding check rather than report a false failure.
    """
    if collection_name in _CACHE:
        return _CACHE[collection_name]

    ids: frozenset[str] = frozenset()
    versions: frozenset[str] = frozenset()
    try:
        from app.services.vector_store import _get_client

        collection = _get_client().get_collection(name=collection_name)
        raw = collection.get(include=["metadatas"])
        ids = frozenset(raw.get("ids") or [])
        versions = frozenset(
            str(m["sdk_version"])
            for m in (raw.get("metadatas") or [])
            if m and m.get("sdk_version")
        )
    except Exception:
        ids, versions = frozenset(), frozenset()

    _CACHE[collection_name] = (ids, versions)
    return ids, versions


def corpus_chunk_ids(collection_name: str) -> frozenset[str]:
    """Every chunk id that actually exists in the collection."""
    return load_corpus_facts(collection_name)[0]


def accepted_version_values(collection_name: str) -> frozenset[str]:
    """Every ``sdk_version`` value the retrieval filter can actually match."""
    return load_corpus_facts(collection_name)[1]
