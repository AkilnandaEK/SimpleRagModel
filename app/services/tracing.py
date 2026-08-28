"""
app/services/tracing.py
-----------------------
Persistent per-request trace collection for the RAG query pipeline.

Each /query request appends exactly one JSON object (one line) to
``traces/traces.jsonl``.  Traces are *never* overwritten — the file is
only ever opened in append mode.

This module is intentionally dependency-free (stdlib only) so it has
zero impact on the existing RAG pipeline.  It contains no knowledge of
retrieval, embedding, or prompt construction — it only stores and loads
serialised trace dicts.

Trace schema
------------
Every trace is a flat dict with these top-level keys:

    trace_id        str   — unique UUID4 per request
    timestamp       str   — ISO-8601 UTC, millisecond precision
    question        str   — the exact user question received
    prompt_version  str   — which version of the prompt was used
    model           str   — Gemini model name from settings
    model_parameters  dict — generation config (empty {} if none configured)
    collection_name str   — which collection was queried
    top_k           int   — effective retrieval depth
    retrieved_chunks  list[dict] — chunk_id, rank, distance, source_file
    prompt          str   — the exact prompt string sent to Gemini
    raw_output      str   — un-stripped Gemini response text
    answer          str   — the final answer returned to the user
    response_status str   — "answered" or "refused" (model-level classification)
    status          str   — "success" or "error" (request-level status)
    error           dict  — present only when status == "error"

No API keys, secrets, or .env values are ever written to traces.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings

#: Which prompt version produced this trace.  Bump this string whenever the
#: prompt wording changes so traces are reproducible against a known version.
PROMPT_VERSION: str = "v1"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _traces_dir() -> Path:
    """Return the directory that stores the JSONL trace log."""
    return Path(settings.traces_dir)


def get_traces_path() -> Path:
    """Return the full path to the traces JSONL file."""
    return _traces_dir() / "traces.jsonl"


def ensure_traces_dir() -> Path:
    """Create the traces directory (and parents) if it doesn't exist."""
    directory = _traces_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# ID / timestamp generation
# ---------------------------------------------------------------------------

def new_trace_id() -> str:
    """Generate a unique trace ID using UUID4 (RFC 4122)."""
    return str(uuid4())


def utc_timestamp() -> str:
    """Return the current UTC time as ISO-8601 with millisecond precision.

    Example: ``2026-08-26T12:30:45.123Z``
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Trace persistence (JSONL append-only)
# ---------------------------------------------------------------------------

def save_trace(trace: dict[str, Any]) -> None:
    """
    Append a single trace dict as one JSON line to the traces JSONL file.

    The traces directory is created automatically if it does not exist.
    Previous traces are **never** overwritten — the file is opened in
    append mode only.
    """
    ensure_traces_dir()
    traces_path = get_traces_path()
    line = json.dumps(trace, ensure_ascii=False)
    with open(traces_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_trace(trace_id: str) -> dict[str, Any] | None:
    """
    Load a single trace by its ``trace_id`` from the JSONL file.

    Returns the trace dict, or ``None`` if no trace with that ID exists.
    """
    traces_path = get_traces_path()
    if not traces_path.exists():
        return None

    with open(traces_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("trace_id") == trace_id:
                return obj
    return None


def load_traces() -> list[dict[str, Any]]:
    """Load all traces from the JSONL file (ordered by file position)."""
    traces_path = get_traces_path()
    if not traces_path.exists():
        return []

    traces: list[dict[str, Any]] = []
    with open(traces_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return traces
