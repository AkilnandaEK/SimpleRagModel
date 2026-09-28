"""MCP server that fronts the project's existing RAG tools over the reference corpus.

This server is a thin transport adapter — it contains no retrieval logic of its
own. Every tool delegates to the functions already in ``tools/``:

    tools.reference_search.reference_search   -> hybrid ChromaDB retrieval
    tools.chunk_retrieval.chunk_retrieval     -> chunk lookup + surrounding context
    app.services.vector_store.list_collections-> collection inventory

Transport: stdio, so any MCP client can launch it.

Two stdio-server requirements are handled here:

1. Expensive imports (``chromadb``, ``sentence-transformers``) and the embedding
   model are loaded once at startup, on the main thread, *before* the event loop
   starts. Importing them lazily inside a tool body is what made the first tool
   call stall for minutes.
2. ``sys.stdout`` is the JSON-RPC transport, so it must carry protocol frames
   only. Every ``print()`` in the application (ChromaDB, sentence-transformers,
   ``app.services.*``) is redirected to stderr, which keeps diagnostics visible
   without corrupting the stream. No application file needs to change.

Configuration (environment variables, all optional):
    DOC_SEARCH_REPO_ROOT   project root to run from (default: this file's parent dir)
    DOC_SEARCH_COLLECTION  default collection   (default: sdk-v3-strategy-b)
    DOC_SEARCH_TOP_K       default result count  (default: 5)
    DOC_SEARCH_PREWARM     '0' to skip model pre-loading (default: pre-load)
"""

from __future__ import annotations

import os
import sys
import time
from io import TextIOWrapper
from pathlib import Path
from typing import Any

# ── stdout is the JSON-RPC channel: claim it, then point print() at stderr ──
_PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr

REPO_ROOT = Path(
    os.getenv("DOC_SEARCH_REPO_ROOT") or Path(__file__).resolve().parent.parent
).resolve()

# Settings load ``./.env`` and ChromaDB lives at ``./chroma_db`` — both are
# relative, so the server must run from the project root regardless of where the
# MCP client happens to have been launched from.
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COLLECTION = os.getenv("DOC_SEARCH_COLLECTION", "sdk-v3-strategy-b")
DEFAULT_TOP_K = int(os.getenv("DOC_SEARCH_TOP_K", "5"))
PREWARM = os.getenv("DOC_SEARCH_PREWARM", "1") != "0"


def _log(message: str) -> None:
    """Diagnostics go to stderr; stdout is reserved for the protocol."""
    print(message, file=sys.stderr, flush=True)


# ── Expensive startup imports, on the main thread, before the event loop ────
import anyio  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from app.services.embedder import _get_model  # noqa: E402
from app.services.vector_store import _get_client  # noqa: E402
from app.services.vector_store import list_collections as _list_collections  # noqa: E402
from tools.chunk_retrieval import ChunkRetrievalInput, chunk_retrieval  # noqa: E402
from tools.reference_search import ReferenceSearchInput, reference_search  # noqa: E402


class StderrSafeMCP(FastMCP):
    """FastMCP whose stdio transport keeps the real stdout and logs to stderr."""

    async def run_stdio_async(self) -> None:
        stream = anyio.wrap_file(
            TextIOWrapper(_PROTOCOL_STDOUT.buffer, encoding="utf-8", errors="replace")
        )
        async with stdio_server(stdout=stream) as (read_stream, write_stream):
            await self._mcp_server.run(
                read_stream,
                write_stream,
                self._mcp_server.create_initialization_options(),
            )


mcp = StderrSafeMCP("doc-search")


def _prewarm() -> None:
    """Load ChromaDB and the embedding model before serving the first request."""
    started = time.time()
    _log(f"[doc-search] repo root: {REPO_ROOT}")
    _log(f"[doc-search] collection: {COLLECTION}")
    try:
        _get_client()
        _log(f"[doc-search] ChromaDB ready at {time.time() - started:.1f}s")
    except Exception as exc:  # noqa: BLE001 - report, do not abort startup
        _log(f"[doc-search] ChromaDB unavailable: {exc}")
    if PREWARM:
        try:
            _get_model()
            _log(f"[doc-search] embedding model ready at {time.time() - started:.1f}s")
        except Exception as exc:  # noqa: BLE001
            _log(f"[doc-search] embedding model unavailable: {exc}")
    _log(f"[doc-search] startup complete in {time.time() - started:.1f}s")


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else dict(model)


def _sources(collection_name: str) -> list[dict[str, Any]]:
    collection = _get_client().get_collection(name=collection_name)
    data = collection.get(include=["metadatas"])

    grouped: dict[str, int] = {}
    for meta in data.get("metadatas") or []:
        name = (meta or {}).get("source_file") or (meta or {}).get("source") or "unknown"
        grouped[name] = grouped.get(name, 0) + 1

    return [
        {"source_file": name, "chunks": count}
        for name, count in sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


@mcp.tool()
def list_collections() -> dict[str, Any]:
    """List every ChromaDB collection available to search, with chunk counts."""
    return {"collections": _list_collections(), "default_collection": COLLECTION}


@mcp.tool()
def list_documents(collection_name: str = COLLECTION) -> dict[str, Any]:
    """List the source documents indexed in a collection, with per-file chunk counts."""
    documents = _sources(collection_name)
    return {
        "collection": collection_name,
        "document_count": len(documents),
        "documents": documents,
    }


@mcp.tool()
def search_documents(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    version: str | None = None,
    target_files: list[str] | None = None,
    collection_name: str = COLLECTION,
) -> dict[str, Any]:
    """Search the reference corpus for chunks matching the query.

    Uses the project's hybrid retrieval (vector + keyword) over ChromaDB.

    Args:
        query: natural-language question or keywords to search for.
        top_k: maximum number of results to return (1-20).
        version: optional metadata filter, e.g. 'v3'.
        target_files: optional list of source filenames to restrict the search to.
        collection_name: ChromaDB collection to search.
    """
    if not query or not query.strip():
        return {"query": query, "results": [], "result_count": 0, "status": "empty query"}

    output = reference_search(
        ReferenceSearchInput(
            query=query.strip(),
            top_k=max(1, min(top_k, 20)),
            version=version,
            target_files=target_files,
        ),
        collection_name=collection_name,
    )
    return _dump(output)


@mcp.tool()
def get_chunk(
    chunk_id: str,
    include_context: bool = True,
    collection_name: str = COLLECTION,
) -> dict[str, Any]:
    """Retrieve one chunk verbatim by its ID, optionally with surrounding context.

    Args:
        chunk_id: the chunk ID returned by ``search_documents``.
        include_context: also return up to 5 neighbouring chunks from the same file.
        collection_name: ChromaDB collection to read from.
    """
    output = chunk_retrieval(
        ChunkRetrievalInput(
            chunk_id=chunk_id,
            collection_name=collection_name,
            include_context=include_context,
        )
    )
    return _dump(output)


if __name__ == "__main__":
    _prewarm()
    mcp.run()
