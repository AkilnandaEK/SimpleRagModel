# RAG System — API Reference

A **backend-only** Retrieval-Augmented Generation (RAG) system built with:

| Component | Technology |
|---|---|
| API Framework | FastAPI + Uvicorn |
| PDF Parsing | PyMuPDF (fitz) |
| Chunking | Context-Aware Chunker (preserves document structure) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, free) |
| Vector Store | ChromaDB (local persistent) |
| LLM | Google Gemini (`gemini-2.0-flash`) |

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- A Gemini API key → [Get one here](https://aistudio.google.com/app/apikey)

### 2. Install dependencies

```powershell
cd p:\week3
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure environment

```powershell
Copy-Item .env.example .env
# Edit .env and set your GEMINI_API_KEY
notepad .env
```

### 4. Run the server

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## API Endpoints

### `POST /upload`

Upload and index a PDF document.

**Form fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | ✅ | PDF file |
| `collection_name` | string | ❌ | Custom name (defaults to filename) |
| `chunk_size` | int | ❌ | Override chunk size in chars (default: 512) |
| `chunk_overlap` | int | ❌ | Override chunk overlap (default: 64) |

**Example (curl):**
```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@my_document.pdf" \
  -F "collection_name=my-doc"
```

**Response:**
```json
{
  "status": "ok",
  "collection_name": "my-doc",
  "filename": "my_document.pdf",
  "chunks_stored": 47,
  "chunk_size": 512,
  "chunk_overlap": 64
}
```

---

### `POST /query`

Ask a question about an indexed document.

**Request body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| `question` | string | ✅ | Your question |
| `collection_name` | string | ✅ | Which document to search |
| `top_k` | int | ❌ | Number of chunks to use as context (default: 5) |

**Example (curl):**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the main findings of this document?",
    "collection_name": "my-doc",
    "top_k": 5
  }'
```

**Response:**
```json
{
  "answer": "The document discusses ...",
  "collection_name": "my-doc",
  "question": "What are the main findings of this document?",
  "chunks_used": 5,
  "sources": [
    {
      "chunk_id": "my_document.pdf__chunk_3",
      "text": "...",
      "distance": 0.1234
    }
  ]
}
```

---

### `GET /collections`

List all indexed documents.

```bash
curl http://localhost:8000/collections
```

---

### `DELETE /collections/{name}`

Remove a document index permanently.

```bash
curl -X DELETE http://localhost:8000/collections/my-doc
```

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Your Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model to use |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Where ChromaDB stores data |
| `CHUNK_SIZE` | `512` | Characters per chunk |
| `CHUNK_OVERLAP` | `64` | Overlap between chunks |
| `TOP_K` | `5` | Chunks retrieved per query |
| `GOLDEN_SET_PATH` | `./eval/golden_set.sdk-v3.json` | Golden set used by `/eval/*` |

---

## Retrieval Evaluation — MRR

**Mean Reciprocal Rank** scores how high up the ranking the *first* relevant chunk
appears:

```
RR(query) = 1 / rank_of_first_relevant_chunk    (0.0 if it never appears)
MRR       = mean(RR) across all graded queries
```

Rank 1 → `1.0`, rank 2 → `0.5`, rank 5 → `0.2`. Only the first hit counts, so a
second relevant chunk further down does not change the score.

Because retrieval is truncated at `top_k`, the result is strictly **MRR@k** —
always report the `k` you evaluated at.

### Dev / test splits

Every golden query carries a `split`:

| Split | Use |
|---|---|
| `dev` | Tune against this freely — chunking, `RRF_K`, `top_k`, prompt |
| `test` | Held out; check it only to confirm a change generalised |

The report **always** includes a per-split breakdown, even when scoring
everything, so a dev-set gain that doesn't transfer to test is visible instead of
being averaged away. The shipped set is stratified — both splits span all six
source documents.

### 1. Write a golden set

A JSON file pairing each question with the chunk IDs that genuinely answer it.
Chunk IDs follow the `<source_filename>__chunk_<index>` scheme written by
`vector_store.add_chunks()`.

```json
{
  "collection_name": "sdk-v3-strategy-a",
  "default_split": "test",
  "queries": [
    {
      "id": "Q1",
      "split": "dev",
      "question": "How do I authenticate with the v3 SDK?",
      "expected_chunk_ids": ["v3_sdk_corpus__chunk_0", "v3_sdk_corpus__chunk_1"]
    }
  ]
}
```

| Field | Required | Description |
|---|---|---|
| `id` | ❌ | Query label (auto-assigned `Q1`, `Q2`… if omitted) |
| `question` | ✅ | The query text |
| `expected_chunk_ids` | ✅ | Relevant chunk IDs (`expected_chunk_id` also accepted for a single ID) |
| `split` | ❌ | `dev` or `test`; falls back to `default_split`, then `test` |
| `sdk_version` | ❌ | Applies the same `{"sdk_version": …}` metadata filter as `POST /query` |

Rejected **at load time**: a query with no expected chunk IDs (MRR is undefined
for an ungraded query, and scoring it `0.0` would silently depress the average),
an unknown split name, an empty question, or a duplicate `id`.

> **A golden set belongs to one corpus.** Chunk IDs encode the source filename
> *and* the chunk index, so scoring a golden set against another collection
> returns `0.0` everywhere. That case is rejected with an explanatory error
> rather than reported as a score. The one thing this can't catch: re-chunking
> the *same* document keeps the IDs valid while moving the content behind them,
> which quietly lowers the score — re-grade after any chunking change.

Path is configurable via `GOLDEN_SET_PATH`; the shipped 12-query example lives at
`eval/golden_set.sdk-v3.json`.

### 2. Run it

No server needed — the script drives the real retrieval stack (embedder → BM25 +
vector → RRF) directly. The collection must already be indexed.

```powershell
python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json
python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json --split dev
python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json --top-k 3
python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json --json eval/mrr_report.json
```

| Flag | Default | Description |
|---|---|---|
| `--golden-set` | *(required)* | Path to the golden-set JSON |
| `--collection` | from golden set | Overrides `collection_name` |
| `--top-k` | `settings.top_k` | Retrieval cutoff *k* |
| `--split` | all | Restrict to `dev` or `test` |
| `--json` | — | Also write the full per-query report to this path |

Output — per-query reciprocal rank, the split breakdown, and any query that
retrieved nothing relevant:

```
  QID    Split       RR   Rank  Question
  Q8     dev     1.0000      1  What does ClientConfig manage?
  Q9     test    0.5000      2  Which environment variable sets the SDK…
  Q11    test    0.2500      4  Which exception is raised when credenti…

  MRR@5 [dev ] = 1.0000  (n=6)
  MRR@5 [test] = 0.7917  (n=6)
  MRR@5 [all ] = 0.8958  (n=12)
```

### 3. Or use the API / Web UI

| Endpoint | Description |
|---|---|
| `GET /eval/golden-set` | The graded query set and its split sizes — no retrieval run |
| `GET /eval/mrr` | Scores the golden set. Query params: `collection_name`, `top_k`, `split` |

```bash
curl "http://localhost:8000/eval/mrr?split=test&top_k=3"
```

In the Flutter UI, the **MRR** button in the chat header opens the evaluation
dialog: overall / dev / test score cards, the full golden-set table (split badge,
expected chunks, hit rank, RR per query), and a miss breakdown showing what was
retrieved instead. The split and `top_k` dropdowns re-run the evaluation live.

### Using the metric directly

`app/services/mrr.py` keeps the maths pure and dependency-free, so it can score
any ranking — not just this retriever:

```python
from app.services.mrr import reciprocal_rank, mean_reciprocal_rank

reciprocal_rank(["a", "b", "c"], relevant_ids=["b"])   # 0.5
mean_reciprocal_rank([1.0, 0.5, 0.0])                  # 0.5
```

---

## Project Structure

```
week3/
├── app/
│   ├── core/
│   │   └── config.py            # Settings from .env
│   ├── routes/
│   │   ├── upload.py            # POST /upload
│   │   ├── query.py             # POST /query, GET/DELETE /collections
│   │   └── evaluation.py        # GET /eval/mrr, GET /eval/golden-set
│   ├── services/
│   │   ├── chunker.py           # PDF extraction + text splitting
│   │   ├── structure_chunker.py # Context-aware structural chunking
│   │   ├── embedder.py          # sentence-transformers wrapper
│   │   ├── hybrid_retrieval.py  # BM25 + RRF over the vector ranking
│   │   ├── mrr.py               # Mean Reciprocal Rank evaluation
│   │   └── vector_store.py      # ChromaDB CRUD
│   └── main.py                  # FastAPI app entry point
├── eval/
│   └── golden_set.sdk-v3.json   # Graded queries for MRR (dev / test splits)
├── scripts/
│   └── eval_mrr.py              # CLI: python scripts/eval_mrr.py --golden-set …
├── frontend/lib/widgets/
│   └── mrr_view.dart            # MRR dialog (golden set + split scores)
├── chroma_db/                   # Auto-created: persistent vector store
├── .env                         # Your config (never commit this!)
├── .env.example                 # Template
├── requirements.txt
└── README.md
```
