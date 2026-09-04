"""
app/core/config.py
------------------
Centralised settings loaded from the .env file.
All tuneable parameters live here — change them in .env, not in code.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Accepted values for LLM_PROVIDER.
VALID_PROVIDERS = ("gemini", "groq")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM Provider Selection ───────────────────────────────────
    llm_provider: str = "gemini"

    # ── Gemini ──────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── Groq ────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

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

    # ── Tracing ──────────────────────────────────────────────────
    traces_dir: str = "./traces"

    @model_validator(mode="after")
    def _validate_provider(self) -> "Settings":
        if self.llm_provider not in VALID_PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider!r} is not supported. "
                f"Valid values: {', '.join(VALID_PROVIDERS)}"
            )
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return self

    @property
    def active_model(self) -> str:
        """Return the model name for the currently selected provider."""
        if self.llm_provider == "gemini":
            return self.gemini_model
        return self.groq_model


# Single shared instance — import this everywhere
settings = Settings()
