"""
app/services/llm_provider.py
-----------------------------
Thin abstraction over LLM providers so the RAG pipeline is provider-agnostic.

Call ``generate_answer(prompt)`` to get a ``LlmResult``.  The active provider
is chosen exclusively via the ``LLM_PROVIDER`` configuration value.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass
class LlmResult:
    """Uniform return type for all LLM providers."""

    provider: str
    model: str
    raw_text: str
    model_parameters: dict


def generate_answer(prompt: str) -> LlmResult:
    """Send *prompt* to the active LLM provider and return the result."""
    provider = settings.llm_provider
    if provider == "gemini":
        return _gemini_generate(prompt)
    elif provider == "groq":
        return _groq_generate(prompt)
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")


# ── Gemini ────────────────────────────────────────────────────────────────────

def _gemini_generate(prompt: str) -> LlmResult:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)
    response = model.generate_content(prompt)

    config = getattr(model, "_generation_config", None)
    model_parameters: dict = {}
    if config:
        try:
            model_parameters = dict(config)
        except (TypeError, ValueError):
            pass

    return LlmResult(
        provider="gemini",
        model=settings.gemini_model,
        raw_text=response.text,
        model_parameters=model_parameters,
    )


# ── Groq ─────────────────────────────────────────────────────────────────────

def _groq_generate(prompt: str) -> LlmResult:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = response.choices[0].message.content

    return LlmResult(
        provider="groq",
        model=settings.groq_model,
        raw_text=raw_text,
        model_parameters={},
    )
