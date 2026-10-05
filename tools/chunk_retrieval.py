"""
tools/chunk_retrieval.py
-------------------------------
Tool 2: Retrieve a specific reference chunk/document section after search identifies a source.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.vector_store import query_chunks, _get_client

#: Expected, *recoverable* storage failures. Anything outside this set is treated
#: as a programming error and deliberately allowed to propagate with its stack
#: trace, so bugs are not laundered into a "recoverable" result.
from chromadb.errors import ChromaError, NotFoundError

#: Broader set for "the store exists but is not usable right now" — a bad
#: CHROMA_PERSIST_DIR, an sqlite lock, or a permissions problem on the DB file.
STORE_UNAVAILABLE = (ChromaError, OSError)

#: Value of ``status`` when a chunk was read but its neighbours could not be.
STATUS_FOUND = "found"
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"

#: Machine-readable ``error_kind`` values, so callers can branch without parsing
#: a human-readable message.
KIND_COLLECTION_NOT_FOUND = "collection_not_found"
KIND_STORE_UNAVAILABLE = "store_unavailable"
KIND_CHUNK_NOT_FOUND = "chunk_not_found"
KIND_CONTEXT_UNAVAILABLE = "context_unavailable"
KIND_RETRIEVAL_FAILED = "retrieval_failed"


# ── Input Schema ─────────────────────────────────────────────────────────────

class ChunkRetrievalInput(BaseModel):
    chunk_id: str = Field(..., min_length=1, description="The chunk ID to retrieve.")
    collection_name: str = Field(default="sdk-v3-strategy-b", description="Collection to search in.")
    include_context: bool = Field(default=True, description="Whether to include surrounding chunks for context.")


# ── Output Schema ────────────────────────────────────────────────────────────

class ChunkContent(BaseModel):
    chunk_id: str
    text: str
    source_file: str | None = None
    page_id: str | None = None
    section: str | None = None
    metadata: dict[str, Any] = {}


class ChunkRetrievalOutput(BaseModel):
    """Result of a chunk lookup.

    ``status`` is always one of ``"found"``, ``"not_found"`` or ``"error"`` — a
    closed set a caller can switch on. Diagnostics live in ``error_kind``,
    ``detail`` and ``recoverable`` rather than being packed into ``status``.
    """

    requested_chunk_id: str
    chunk: ChunkContent | None = None
    context_chunks: list[ChunkContent] = []
    status: str  # "found", "not_found", or "error"
    #: Stable failure category, or None on success. Set even when ``status`` is
    #: "found" but ``context_chunks`` could not be completed.
    error_kind: str | None = None
    #: Actionable, human-readable explanation of what failed and what to try.
    detail: str = ""
    #: True when the caller can fix this by changing its request (retry with a
    #: different collection/chunk_id, or retry without context). False means the
    #: failure is an environment or infrastructure problem, not a bad request.
    recoverable: bool = False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _failure(
    chunk_id: str,
    kind: str,
    detail: str,
    *,
    recoverable: bool,
) -> ChunkRetrievalOutput:
    return ChunkRetrievalOutput(
        requested_chunk_id=chunk_id,
        chunk=None,
        context_chunks=[],
        status=STATUS_ERROR,
        error_kind=kind,
        detail=detail,
        recoverable=recoverable,
    )


# ── Tool Implementation ──────────────────────────────────────────────────────

def chunk_retrieval(input_data: ChunkRetrievalInput) -> ChunkRetrievalOutput:
    """Retrieve one chunk by ID from the vector store, with optional neighbours.

    Purpose
        Second step of the retrieve-then-read pattern: ``reference_search``
        returns ranked ``chunk_id`` values, and this tool fetches one of them
        verbatim so the agent can quote it as evidence.

    Args:
        input_data: ``ChunkRetrievalInput`` — ``chunk_id`` (required, non-empty),
            ``collection_name`` (default ``"sdk-v3-strategy-b"``) and
            ``include_context`` (default ``True``).

    Returns:
        ``ChunkRetrievalOutput`` whose ``status`` is exactly one of:

        * ``"found"``   — ``chunk`` is populated. ``context_chunks`` holds up to
          5 chunks from the same ``source_file``, and may legitimately be empty.
        * ``"not_found"`` — the collection exists but holds no such ID.
        * ``"error"``   — nothing could be read; ``chunk`` is ``None``.

    Error handling
        Expected storage failures are converted into a ``status="error"`` result
        carrying ``error_kind``, a ``detail`` the caller can act on, and
        ``recoverable=True``:

        ==========================  ========================  ==============
        ``error_kind``              meaning                    fix
        ==========================  ========================  ==============
        ``collection_not_found``    no such collection         re-ingest, or
                                                                 pass another
                                                                 ``collection_name``
        ``store_unavailable``       DB unreachable / locked    check
                                                                 ``CHROMA_PERSIST_DIR``,
                                                                 then retry
        ``chunk_not_found``         ID absent from collection re-run the search
                                                                 that produced the
                                                                 ID
        ``retrieval_failed``        the read itself failed     retry
        ``context_unavailable``     chunk read, neighbours     retry with
                                  not                        ``include_context=False``
        ==========================  ========================  ==============

        ``context_unavailable`` keeps ``status="found"`` because the primary
        chunk was genuinely retrieved; only the optional context is missing.

        Unexpected exceptions (a bug in this code, ``MemoryError``,
        ``KeyboardInterrupt``) are **not** caught — they propagate with their
        stack trace so a real defect is never reported to the model as a
        recoverable tool error.

    Limitations
        * Context lookup scans the entire collection and then filters by
          ``source_file`` in Python, so ``include_context=True`` is O(collection
          size) per call. It returns the first 5 matches in ChromaDB's order,
          not strictly the adjacent chunks.
        * Chunk IDs are collection-scoped. An ID retrieved from collection A
          will report ``chunk_not_found`` against collection B.
        * Only one chunk is read per call; there is no batch variant.
    """
    chunk_id = input_data.chunk_id

    # Step 1 — acquire the collection. A missing collection and an unusable
    # store need different fixes, so they are separated instead of being
    # collapsed into one catch-all message.
    try:
        client = _get_client()
    except STORE_UNAVAILABLE as exc:
        return _failure(
            chunk_id,
            KIND_STORE_UNAVAILABLE,
            f"Could not open the ChromaDB store: {exc}. Check that CHROMA_PERSIST_DIR "
            f"points at a readable, writable directory and that no other process holds "
            f"a lock on it, then retry.",
            recoverable=True,
        )

    try:
        collection = client.get_collection(name=input_data.collection_name)
    except NotFoundError:
        return _failure(
            chunk_id,
            KIND_COLLECTION_NOT_FOUND,
            f"Collection {input_data.collection_name!r} does not exist. List the "
            f"available collections first and retry with a valid collection_name, or "
            f"upload a document to create it.",
            recoverable=True,
        )
    except STORE_UNAVAILABLE as exc:
        return _failure(
            chunk_id,
            KIND_STORE_UNAVAILABLE,
            f"Collection {input_data.collection_name!r} exists but could not be opened: "
            f"{exc}. This is a storage problem rather than a missing collection — check "
            f"CHROMA_PERSIST_DIR and retry.",
            recoverable=True,
        )

    # Step 2 — read the requested chunk.
    try:
        result = collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas"],
        )
    except (ChromaError, OSError, KeyError) as exc:
        return _failure(
            chunk_id,
            KIND_RETRIEVAL_FAILED,
            f"Reading chunk {chunk_id!r} from {input_data.collection_name!r} failed: "
            f"{exc}. The collection is reachable, so this is usually transient — "
            f"retry, or re-embed the corpus if it persists.",
            recoverable=True,
        )

    if not result.get("ids") or not result["ids"][0]:
        return ChunkRetrievalOutput(
            requested_chunk_id=chunk_id,
            chunk=None,
            context_chunks=[],
            status=STATUS_NOT_FOUND,
            error_kind=KIND_CHUNK_NOT_FOUND,
            detail=(
                f"Chunk {chunk_id!r} is not in collection {input_data.collection_name!r}. "
                f"Chunk IDs are collection-scoped, so an ID from a different collection "
                f"will not resolve here — re-run reference_search against this collection."
            ),
            recoverable=True,
        )

    doc = result["documents"][0]
    # ChromaDB returns ``metadatas: [None]`` for a chunk stored without any
    # metadata, so the element itself can be None even when the list is truthy.
    meta = (result["metadatas"][0] if result.get("metadatas") else None) or {}

    chunk = ChunkContent(
        chunk_id=chunk_id,
        text=doc,
        source_file=meta.get("source_file") or meta.get("source"),
        page_id=str(meta.get("page_id") or meta.get("page") or ""),
        section=meta.get("section"),
        metadata=meta,
    )

    # Step 3 — optional neighbours. Previously a failure here was swallowed, so
    # a broken scan was indistinguishable from "this chunk has no neighbours".
    context_chunks: list[ChunkContent] = []
    context_error: str | None = None
    if input_data.include_context:
        source_file = meta.get("source_file") or meta.get("source")
        if source_file:
            try:
                all_docs = collection.get(
                    include=["documents", "metadatas"],
                )
                for cid, cdoc, cmeta in zip(
                    all_docs["ids"], all_docs["documents"], all_docs.get("metadatas") or []
                ):
                    if cid == chunk_id:
                        continue
                    csrc = (cmeta or {}).get("source_file") or (cmeta or {}).get("source")
                    if csrc == source_file:
                        context_chunks.append(ChunkContent(
                            chunk_id=cid,
                            text=cdoc,
                            source_file=csrc,
                            page_id=str((cmeta or {}).get("page_id") or (cmeta or {}).get("page") or ""),
                            section=(cmeta or {}).get("section"),
                            metadata=cmeta or {},
                        ))
            except (ChromaError, OSError, KeyError, TypeError) as exc:
                # The requested chunk was read successfully, so the result stays
                # "found" — but the caller is told the context is incomplete
                # instead of being handed a silently empty list.
                context_error = (
                    f"Context lookup failed for {source_file!r}: {exc}. The requested chunk "
                    f"was returned in full; retry with include_context=False if the "
                    f"neighbouring chunks are not required."
                )

    return ChunkRetrievalOutput(
        requested_chunk_id=chunk_id,
        chunk=chunk,
        context_chunks=context_chunks[:5],
        status=STATUS_FOUND,
        error_kind=KIND_CONTEXT_UNAVAILABLE if context_error else None,
        detail=context_error or "",
        recoverable=context_error is not None,
    )
