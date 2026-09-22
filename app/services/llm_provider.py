"""
app/services/llm_provider.py
-----------------------------
Thin abstraction over LLM providers so the RAG pipeline is provider-agnostic.

Call ``generate_answer(prompt)`` to get a ``LlmResult``.  The active provider
is chosen exclusively via the ``LLM_PROVIDER`` configuration value.

``generate_answer_with_usage`` is the token-counting variant used by the Week 7
benchmark (agent + workflow) so both architectures share this same wrapper.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class LlmResult:
    """Uniform return type for all LLM providers."""

    provider: str
    model: str
    raw_text: str
    model_parameters: dict
    input_tokens: int = 0
    output_tokens: int = 0


def generate_answer(prompt: str) -> LlmResult:
    """Send *prompt* to the active LLM provider and return the result."""
    provider = settings.llm_provider
    if provider == "gemini":
        return _gemini_generate(prompt)
    elif provider == "groq":
        return _groq_generate(prompt)
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")


def generate_answer_with_usage(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    tool_choice: str | None = "none",
) -> LlmResult:
    """Send *prompt* to a provider/model and capture real token usage.

    ``provider`` and ``model`` default to the active app settings but may be
    overridden (the benchmark can target a different model than ``POST /query``).
    ``tool_choice="none"`` stops models that wrap ReAct-style output into native
    tool calls, which would break the manually-implemented agent loop.
    """
    active = provider or settings.llm_provider
    if active == "gemini":
        return _gemini_generate(prompt, model=model or settings.gemini_model)
    elif active == "groq":
        return _groq_generate(prompt, model=model or settings.groq_model, tool_choice=tool_choice)
    raise ValueError(f"Unsupported LLM_PROVIDER: {active!r}")


# ── Gemini ────────────────────────────────────────────────────────────────────

def _gemini_generate(prompt: str, model: str | None = None) -> LlmResult:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model_name = model or settings.gemini_model
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)

    config = getattr(model, "_generation_config", None)
    model_parameters: dict = {}
    if config:
        try:
            model_parameters = dict(config)
        except (TypeError, ValueError):
            pass

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    return LlmResult(
        provider="gemini",
        model=model_name,
        raw_text=response.text,
        model_parameters=model_parameters,
        input_tokens=input_tokens or (len(prompt) // 4),
        output_tokens=output_tokens or (len(response.text) // 4),
    )


# ── Groq ─────────────────────────────────────────────────────────────────────

def _groq_generate(prompt: str, model: str | None = None, tool_choice: str | None = None) -> LlmResult:
    """Call Groq, recovering the model's decision when it answers with a tool call.

    Tool-tuned models (the ``openai/gpt-oss-*`` family in particular) respond to
    a ReAct prompt by emitting a *native* function call rather than the
    line-format text the prompt asks for. Because this request declares no
    ``tools``, Groq rejects that with a 400 ``tool_use_failed`` — note this
    happens whether or not ``tool_choice`` is sent, so the error's
    "Tool choice is none, but model called a tool" wording is misleading.

    The rejection body carries ``failed_generation``: the exact call the model
    wanted to make, name and arguments intact. Throwing that away turns a
    perfectly good agent decision into a dead run, so we return it as the
    response text and let the agent's action parser read it.
    """
    from groq import BadRequestError, Groq

    resolved_model = model or settings.groq_model
    client = Groq(api_key=settings.groq_api_key)
    create_args = {
        "model": resolved_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if tool_choice:
        create_args["tool_choice"] = tool_choice

    try:
        response = client.chat.completions.create(**create_args)
    except BadRequestError as exc:
        error = (getattr(exc, "body", None) or {}).get("error", {})
        failed_generation = error.get("failed_generation")
        # Keyed on the payload being present rather than on a specific error
        # code: Groq returns `failed_generation` for several 400s (at least
        # `tool_use_failed` and its output-parsing failures), and in every case
        # it is the model's own text. A 400 without it is a genuine error.
        if not failed_generation:
            raise
        # Token usage is not reported on a rejected call; estimate it so budget
        # accounting and cost telemetry stay roughly honest rather than zero.
        return LlmResult(
            provider="groq",
            model=resolved_model,
            raw_text=failed_generation,
            model_parameters={"recovered_from": "tool_use_failed"},
            input_tokens=len(prompt) // 4,
            output_tokens=len(failed_generation) // 4,
        )

    message = response.choices[0].message
    raw_text = message.content or ""

    # A model that emits a native tool call *successfully* lands here. Normalise
    # it into the same JSON shape the recovery path returns, so the action
    # parser has exactly one extra format to understand rather than two.
    tool_calls = getattr(message, "tool_calls", None)
    if not raw_text and tool_calls:
        call = tool_calls[0].function
        raw_text = json.dumps({"name": call.name, "arguments": call.arguments})

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0

    return LlmResult(
        provider="groq",
        model=resolved_model,
        raw_text=raw_text,
        model_parameters={},
        input_tokens=input_tokens or (len(prompt) // 4),
        output_tokens=output_tokens or (len(raw_text) // 4),
    )
