# Tool documentation and recoverable errors — before & after

**Tool:** `tools/chunk_retrieval.py` → `chunk_retrieval()`
**Before-state source:** `git show HEAD:tools/chunk_retrieval.py` (commit `6543bae`, file last changed in `b90bdd7` "Added Week 7 agent flow and workflow comparison"). The original is recoverable in full, so nothing below is reconstructed or invented.
**After-state:** working tree.

---

## 1. Original behavior and its weakness

The original function is 80 lines with three `except` blocks and a two-line docstring. Four concrete defects were found, each reproduced by running the original code verbatim against a fake ChromaDB client (see §5 for the harness).

| # | Defect | Original code | Observed original behaviour |
|---|---|---|---|
| **W1** | Context-scan failure silently swallowed, producing a **misleading success** | `except Exception:` / `pass` (`HEAD` lines 116–117) | Chunk read succeeds, neighbour scan raises → `status='found'`, `context_chunks=[]`. **Byte-for-byte identical output to "this chunk has no neighbours."** The caller cannot tell a broken scan from an empty one, and will confidently answer from a truncated context. |
| **W2** | One catch-all mislabels every storage failure as "collection not found" | `except Exception as exc: status=f"error: collection not found: {exc}"` (`HEAD` lines 52–58) | A locked/corrupt/unreadable store yields `status='error: collection not found: chroma_db is locked by another process'`. The message points the caller at the wrong fix (re-ingest documents) when the real fix is to release the lock. |
| **W3** | Free text packed into `status`, breaking its own documented enum | `status: str  # "found", "not_found", or "error"` yet emits `f"error: {exc}"` (`HEAD` line 39 vs 57/70) | Callers writing `if out.status == "error":` **never match**, so every error is handled as if it were a hit. |
| **W4** | A chunk stored without metadata crashes with an `AttributeError` | `meta = result["metadatas"][0] if result.get("metadatas") else {}` (`HEAD` line 82) | ChromaDB returns `metadatas: [None]` — a *truthy list containing None* — so `meta` becomes `None` and `meta.get(...)` raises. Uncaught, this is an unexpected programming-style error that kills the whole agent run (`agent/agent_loop.py:470` calls this with no guard). |

**Documentation weakness.** The docstring was the entire contract:

```python
    """
    Retrieve a specific chunk by ID from the vector store.
    Optionally includes context chunks from the same source document.
    """
```

It named no inputs, no defaults (`collection_name="sdk-v3-strategy-b"`, `include_context=True`), no output shape, no `status` values, and no limitations. Since the model reads tool descriptions to choose arguments — the exact root cause documented for Week 8 in `eval/WEEK8_SUBMISSION.md` §4 ("the tool description never says what `version` accepts") — this is the same class of defect.

---

## 2. Exact before-and-after docstring

### BEFORE (`git show HEAD:tools/chunk_retrieval.py`, lines 44–48)

```python
def chunk_retrieval(input_data: ChunkRetrievalInput) -> ChunkRetrievalOutput:
    """
    Retrieve a specific chunk by ID from the vector store.
    Optionally includes context chunks from the same source document.
    """
```

### AFTER (working tree)

```python
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
```

### Output model

```python
# BEFORE
class ChunkRetrievalOutput(BaseModel):
    requested_chunk_id: str
    chunk: ChunkContent | None = None
    context_chunks: list[ChunkContent] = []
    status: str  # "found", "not_found", or "error"

# AFTER
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
```

The three new fields all have defaults, so the model stays backward-compatible and existing construction sites keep working.

---

## 3. Exact before-and-after error-handling behavior

### 3.1 Recoverable vs unexpected — the catch lists

```python
# AFTER — imported from chromadb.errors, not a blanket Exception
from chromadb.errors import ChromaError, NotFoundError

#: Expected, *recoverable* storage failures. Anything outside this set is treated
#: as a programming error and deliberately allowed to propagate with its stack
#: trace, so bugs are not laundered into a "recoverable" result.
STORE_UNAVAILABLE = (ChromaError, OSError)
```

| Step | BEFORE | AFTER |
|---|---|---|
| open store + get collection | `except Exception` → one message | `except NotFoundError` → `collection_not_found`; `except STORE_UNAVAILABLE` → `store_unavailable`; anything else **propagates** |
| read requested chunk | `except Exception` → `"error: retrieval failed: {exc}"` | `except (ChromaError, OSError, KeyError)` → `retrieval_failed` + recovery hint; anything else **propagates** |
| id absent | `status="not_found"`, no detail | `status="not_found"`, `error_kind="chunk_not_found"`, `recoverable=True`, `detail=…` |
| scan neighbours | `except Exception: pass` | `except (ChromaError, OSError, KeyError, TypeError)` → `status` stays `"found"`, `error_kind="context_unavailable"`, `detail=…`; anything else **propagates** |
| metadata is `None` | `AttributeError` escapes | normalised with `or {}` |

### 3.2 Same scenario, both versions

Every row below is **measured output**, not a description. The "BEFORE" column comes from running the verbatim `git HEAD` function against the same fake client; the "AFTER" column is the new test suite.

| Failure scenario | BEFORE | AFTER |
|---|---|---|
| Collection does not exist | `status='error: collection not found: Collection [sdk-v3-strategy-b] does not exist'` | `status='error'`, `error_kind='collection_not_found'`, `recoverable=True`, `detail="…does not exist. List the available collections first and retry with a valid collection_name, or upload a document to create it."` |
| Store locked / unreadable | `status='error: collection not found: chroma_db is locked by another process'` ← **wrong diagnosis** | `status='error'`, `error_kind='store_unavailable'`, `recoverable=True`, `detail="…Check that CHROMA_PERSIST_DIR points at a readable, writable directory and that no other process holds a lock on it, then retry."` |
| Chunk read fails | `status='error: retrieval failed: segment read failed'` | `status='error'`, `error_kind='retrieval_failed'`, `recoverable=True`, `detail="…The collection is reachable, so this is usually transient — retry, or re-embed the corpus if it persists."` |
| **Neighbour scan crashes** | `status='found'`, `context_chunks=[]` ← **indistinguishable from "no neighbours"** | `status='found'`, `error_kind='context_unavailable'`, `recoverable=True`, `detail="…retry with include_context=False if the neighbouring chunks are not required."` |
| Chunk stored with no metadata | `AttributeError: 'NoneType' object has no attribute 'get'` ← **uncaught** | `status='found'`, `chunk.text='text'`, `source_file=None`, `context_chunks=[]` |
| Bug in the tool itself | caught and reported as a tool error | propagates with its stack trace (test: `test_unexpected_exception_propagates_rather_than_being_reported_as_recoverable`) |
| Caller writes `status == "error"` | **never true** — error treated as a hit | **true** for every failure |

### 3.3 Public interface and successful behaviour — preserved

* `ChunkRetrievalInput`, `ChunkContent`, `ChunkRetrievalOutput` names, fields and ordering unchanged; the three added fields are defaulted.
* `chunk_retrieval(input_data: ChunkRetrievalInput) -> ChunkRetrievalOutput` signature unchanged. No caller was updated to compile.
* Success path verified unchanged against the real index: `v3_sdk_corpus__chunk_1` in `sdk-v3-strategy-b` returns `status='found'`, `error_kind=None`, `detail=''`, `recoverable=False`, `source_file='authentication.md'`, `context_chunks=['v3_sdk_corpus__chunk_0', 'v3_sdk_corpus__chunk_2']` — identical to the original.
* `not_found` is still a non-error status, as before.
* The `context_chunks[:5]` cap is unchanged.

**One deliberate, documented trade-off.** `agent/agent_loop.py:481` interpolates only `retrieval_result.status` into its trace observation, so the agent trace now reads `Retrieved chunk. Status: error` where it previously read `Retrieved chunk. Status: error: collection not found: …`. The richer message moved to `detail`. Making the trace show it is a one-line change to the agent core, deliberately **not** made here so the agent stays untouched for the Week 9 MCP work. No evidence is lost: `state.collected_evidence` is only appended when `retrieval_result.chunk` exists, and that is unchanged.

---

## 4. Failure scenario used to test recovery

The `context_unavailable` path is the primary scenario, because it is the one that previously produced a **silently misleading success**.

**Setup.** A fake Chroma collection serves three chunks. An ID-scoped read (`ids=[...]`) succeeds and returns the requested chunk. The subsequent unfiltered full-collection read — the context scan — raises `chromadb.errors.InternalError("full scan failed")`, exactly as a real ChromaDB segment/index read failure would.

**Invocation.**

```python
fake_store(_FakeCollection(_ROWS, fail_context=True))
out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_1"))
```

**Expected recovery behaviour** (asserted in `tests/test_week9.py::test_failed_context_scan_is_surfaced_instead_of_silently_swallowed`):

1. The call does **not** raise — the caller still gets its chunk.
2. `out.status == "found"` — the primary retrieval genuinely succeeded, so the result is honestly still a success.
3. `out.chunk.text == "beta text"` — the requested chunk is complete and usable.
4. `out.error_kind == "context_unavailable"` — the incomplete part is named.
5. `out.recoverable is True` and `out.detail` contains `include_context=False`, i.e. a concrete next action.
6. This is **distinguishable** from the genuinely-empty case, which returns `status="found"`, `error_kind=None`, `detail=""`, `context_chunks=[]`.

Secondary scenarios in the same suite: missing collection vs. unusable store (asserting they are *not* the same kind), failed chunk read, absent chunk ID, metadata-free chunk, the 5-neighbour cap, `include_context=False` skipping the scan entirely, the closed `status` enum, and unexpected-exception propagation.

---

## 5. Test command and actual result

```
> .venv\Scripts\python.exe -m pytest tests\test_week9.py -m "not live" -q
..................................                                       [100%]
34 passed, 2 deselected, 1 warning in 10.14s
```

```
> .venv\Scripts\python.exe -m pytest tests\test_week9.py -m "live" -q
2 passed, 34 deselected, 1 warning in 44.07s
```

```
> .venv\Scripts\python.exe -m pytest tests\ -q
133 passed, 1 warning in 52.73s
```

133 = 97 pre-existing (21 in `test_week7.py`, 76 in `test_week8.py`) + 36 added in `test_week9.py`. No pre-existing test needed changing, and no regression was introduced.

The tests are hermetic: ChromaDB is replaced with an in-test fake via `monkeypatch.setattr(cr, "_get_client", …)`, so the whole `chunk_retrieval` group runs in ~10 s with no index and no network. The 2 deselected `live` tests are the MCP integration ones, not chunk retrieval.

Reproducing the BEFORE column requires the original function, which is at `git show HEAD:tools/chunk_retrieval.py`; it is not kept in the tree.

---

## 6. Remaining limitations

1. **Only this one tool was changed.** `tools/reference_search.py` and `tools/migration_analyzer.py` still use the same `except Exception` / `status=f"error: …"` pattern and the same two-line docstrings. The defects are structural, not local; fixing one tool does not fix the pattern. `reference_search` is arguably worse — it catches embedding failures, which are exactly the errors that should surface during development.
2. **The agent trace shows only `status`.** `detail` is not surfaced in `agent/agent_loop.py:481`; see the trade-off note in §3.3. A one-line change would close this, deliberately deferred to keep the agent core untouched.
3. **`context_unavailable` is detected, not prevented.** The scan is still O(collection size) and still returns the first 5 neighbours in ChromaDB's order rather than the adjacent ones. A real fix needs either a `chunk_index` range query or a precomputed neighbour index; neither is in scope here.
4. **`recoverable` is advisory.** It is a flag the caller must honour. Nothing in the agent loop reads it yet, so the model still sees only `status` in its observation.
5. **`STORE_UNAVAILABLE` includes bare `OSError`.** That is broader than a single ChromaDB type, so an unexpected OS-level bug in the read path would be reported as recoverable. It is kept narrow enough to exclude real defects (`AttributeError`, `TypeError`, `RuntimeError` all propagate) but it is a judgement call, not a proof.
6. **No live-ChromaDB test of the error paths.** The recoverable-error tests use a fake collection, so they assert the mapping logic, not ChromaDB's real exception types against a real 1.5.9 store. The one real-store check is the manual success-path run quoted in §3.3, and the `NotFoundError` type was confirmed against the installed `chromadb` 1.5.9 directly.
