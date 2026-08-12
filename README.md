# RAG System — API Reference

A **backend-only** Retrieval-Augmented Generation (RAG) system built with:

| Component | Technology |
|---|---|
| API Framework | FastAPI + Uvicorn |
| PDF Parsing | PyMuPDF (fitz) |
| Chunking | Custom Recursive Character Splitter |
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

---

## Project Structure

```
week3/
├── app/
│   ├── core/
│   │   └── config.py         # Settings from .env
│   ├── routes/
│   │   ├── upload.py         # POST /upload
│   │   └── query.py          # POST /query, GET/DELETE /collections
│   ├── services/
│   │   ├── chunker.py        # PDF extraction + text splitting
│   │   ├── embedder.py       # sentence-transformers wrapper
│   │   └── vector_store.py   # ChromaDB CRUD
│   └── main.py               # FastAPI app entry point
├── chroma_db/                # Auto-created: persistent vector store
├── .env                      # Your config (never commit this!)
├── .env.example              # Template
├── requirements.txt
└── README.md
```
