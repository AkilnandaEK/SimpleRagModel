"""
app/core/config.py
------------------
Centralised settings loaded from the .env file.
All tuneable parameters live here — change them in .env, not in code.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Gemini ──────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── Embeddings ──────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── ChromaDB ────────────────────────────────────────────────
    chroma_persist_dir: str = "./chroma_db"

    # ── Chunking ────────────────────────────────────────────────
    chunk_size: int = 512
    chunk_overlap: int = 64

    # ── Retrieval ───────────────────────────────────────────────
    top_k: int = 5

    # ── Evaluation ──────────────────────────────────────────────
    golden_set_path: str = "./eval/golden_set.sdk-v3.json"


# Single shared instance — import this everywhere
settings = Settings()
