"""
benchmark/config.py
-------------------
Centralised configuration for the Week 7 benchmark system.
All tuneable parameters live here.

Configuration is read from the shared Week 3 ``.env`` at the project root
(one configuration source). The benchmark reuses the same API keys and model
names as the RAG app, while exposing its own WEEK7_*/BENCHMARK_* overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LLMConfig:
    provider: str = "gemini"
    mode: str = "offline"  # "live" (real provider) or "offline" (observation-driven reasoner)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"


@dataclass
class PricingConfig:
    """Per-token pricing (USD) for cost estimation."""
    input_cost_per_1k_tokens: float = 0.00027
    output_cost_per_1k_tokens: float = 0.00027


@dataclass
class SafetyConfig:
    max_iterations: int = 10
    max_input_tokens: int = 8000
    max_output_tokens: int = 2000
    max_total_tokens: int = 10000
    max_cost_usd: float = 0.50
    timeout_seconds: float = 120.0


@dataclass
class RetrievalConfig:
    top_k: int = 5
    collection_name: str = "sdk-v3-strategy-b"


@dataclass
class BenchmarkConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    golden_set_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "goldensets")
    benchmark_scenario_ids: list[str] = field(default_factory=lambda: [
        "easy:01", "easy:04", "easy:13",
        "medium:02", "medium:05", "medium:14",
        "hard:01", "hard:04", "hard:09", "hard:13",
    ])


def _load_dotenv() -> None:
    """Load the shared project .env so one configuration source covers both the
    RAG app and the benchmark."""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")


def load_config_from_env() -> BenchmarkConfig:
    """Load config from environment variables with sensible defaults.

    The benchmark provider defaults to Gemini because the Groq
    ``openai/gpt-oss-20b`` model auto-wraps ReAct-style structured output into
    native tool calls (raising ``tool_choice is none, but model called a tool``),
    which conflicts with the manually-implemented agent loop. Override with
    ``WEEK7_LLM_PROVIDER=|gemini|groq|`` if you have a Groq model that supports
    free-form structured output.
    """
    import os

    _load_dotenv()

    config = BenchmarkConfig()
    config.llm.provider = os.getenv("WEEK7_LLM_PROVIDER", "gemini")
    config.llm.mode = os.getenv("WEEK7_LLM_MODE", "offline")
    config.llm.groq_api_key = os.getenv("GROQ_API_KEY", "")
    config.llm.groq_model = os.getenv("WEEK7_GROQ_MODEL", os.getenv("GROQ_MODEL", config.llm.groq_model))
    config.llm.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    config.llm.gemini_model = os.getenv("WEEK7_GEMINI_MODEL", os.getenv("GEMINI_MODEL", config.llm.gemini_model))

    golden_set_dir = os.getenv("BENCHMARK_GOLDEN_SET_DIR", "goldensets")
    config.golden_set_dir = Path(golden_set_dir)
    if not config.golden_set_dir.is_absolute():
        config.golden_set_dir = PROJECT_ROOT / config.golden_set_dir

    collection_name = os.getenv("BENCHMARK_COLLECTION_NAME", "sdk-v3-strategy-b")
    config.retrieval.collection_name = collection_name
    return config