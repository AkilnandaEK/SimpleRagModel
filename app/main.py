"""
app/main.py
-----------
FastAPI application entry point.

Startup behaviour:
  - Loads .env settings via pydantic-settings
  - Registers all route modules
  - Pre-warms the embedding model in a background task on first startup
    so the first /upload request isn't slow
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routes import evaluation as evaluation_router
from app.routes import query as query_router
from app.routes import upload as upload_router


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: startup / shutdown hooks
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Pre-warm the sentence-transformer model at startup so the first
    request isn't penalised by model loading time (~1-3 s).
    """
    print("=" * 60)
    print("  RAG System starting up …")
    print(f"  Gemini model   : {settings.gemini_model}")
    print(f"  Embedding model: {settings.embedding_model}")
    print(f"  ChromaDB path  : {settings.chroma_persist_dir}")
    print(f"  Chunk size     : {settings.chunk_size}  |  Overlap: {settings.chunk_overlap}")
    print("=" * 60)

    # Pre-load embedding model (runs in the same thread — acceptable at startup)
    from app.services.embedder import _get_model
    _get_model()

    yield  # Server is running

    print("[main] Shutting down …")


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="RAG System API",
    description=(
        "A Retrieval-Augmented Generation (RAG) backend.\n\n"
        "**Workflow:**\n"
        "1. `POST /upload` — Upload a PDF to index it.\n"
        "2. `POST /query` — Ask a question; Gemini answers from your document.\n"
        "3. `GET /collections` — See all indexed documents.\n"
        "4. `DELETE /collections/{name}` — Remove a document index.\n"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (allow all origins for local dev — lock this down in production) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(upload_router.router)
app.include_router(query_router.router)
app.include_router(evaluation_router.router)

# ── Mount Flutter Web UI static files ─────────────────────────────────────────
frontend_build_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "build", "web")
if os.path.exists(frontend_build_dir):
    app.mount("/app", StaticFiles(directory=frontend_build_dir, html=True), name="flutter_web")


# ─────────────────────────────────────────────────────────────────────────────
# Root health-check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"], summary="Health check")
async def root() -> JSONResponse:
    """Simple health check — confirms the server is running."""
    return JSONResponse(
        content={
            "status": "ok",
            "message": "RAG System is running. Visit /app for the Web UI or /docs for API reference.",
            "web_ui": "/app/",
            "docs_url": "/docs",
            "gemini_model": settings.gemini_model,
            "embedding_model": settings.embedding_model,
        }
    )
