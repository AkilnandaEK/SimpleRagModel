"""
scripts/replay_trace.py
-----------------------
Replay a single stored trace from traces/traces.jsonl.

Usage (from the repo root, with the venv active):

    python scripts/replay_trace.py --trace-id <trace_id>
    python scripts/replay_trace.py --trace-id <trace_id> --replay      # also re-run Gemini

What it does
------------
1. Loads the trace with the given ``trace_id`` from ``traces/traces.jsonl``.
2. Displays the stored question, prompt version, model, and model parameters.
3. Displays the stored retrieved chunks (ID, rank, distance, source).
4. Displays the exact stored prompt.
5. If ``--replay`` is given, re-sends that stored prompt to the same Gemini
   model with the same (empty/default) parameters and captures the output.
6. Displays the replayed output (if requested) and the original output.
7. Indicates whether the outputs match.

Limitations
-----------
- Gemini is a non-deterministic LLM.  Re-running the same prompt will generally
  produce *different* token sequences.  Exact string matching is therefore not
  expected — the comparison is informational only.
- The trace does not store API credentials.  The replay uses the credentials
  found in the environment / .env file, exactly like the production pipeline.
- The trace was captured with the default generation config (no temperature,
  top_p, etc.).  The production code does not configure generation parameters,
  so ``model_parameters`` is ``{}`` and the replay mirrors that.
- Retrieval is *not* re-run during replay.  The stored prompt (which already
  contains the retrieved context) is used verbatim, so the trace is replayable
  without depending on retrieval determinism.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/replay_trace.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.tracing import load_trace  # noqa: E402


def _print_section(title: str, char: str = "=") -> None:
    print()
    print(char * 70)
    print(f"  {title}")
    print(char * 70)


def _print_trace_info(trace: dict) -> None:
    _print_section("TRACE METADATA")
    print(f"  trace_id           : {trace.get('trace_id')}")
    print(f"  timestamp          : {trace.get('timestamp')}")
    print(f"  status             : {trace.get('status')}")
    print(f"  prompt_version     : {trace.get('prompt_version')}")
    print(f"  model              : {trace.get('model')}")
    print(f"  model_parameters   : {trace.get('model_parameters')}")
    print(f"  collection_name    : {trace.get('collection_name')}")
    print(f"  top_k              : {trace.get('top_k')}")
    print(f"  response_status    : {trace.get('response_status')}")


def _print_question(trace: dict) -> None:
    _print_section("ORIGINAL QUESTION")
    print(f"  {trace.get('question', '(none)')}")


def _print_retrieved_chunks(trace: dict) -> None:
    chunks = trace.get("retrieved_chunks", [])
    _print_section(f"RETRIEVED CHUNKS ({len(chunks)} total)")
    if not chunks:
        print("  (none)")
        return
    for ch in chunks:
        chunk_id = ch.get("chunk_id", "?")
        rank = ch.get("rank", "?")
        distance = ch.get("distance")
        source = ch.get("source_file")
        dist_str = f"{distance:.4f}" if distance is not None else "(None — BM25-only)"
        print(f"  Rank {rank:>3} | {chunk_id}")
        print(f"           distance: {dist_str}")
        print(f"           source  : {source or '(unknown)'}")


def _print_prompt(trace: dict) -> None:
    prompt = trace.get("prompt")
    _print_section("STORED PROMPT (exact)")
    if not prompt:
        print("  (prompt was not captured — request failed before prompt construction)")
        return
    print("  ── begin prompt ─────────────────────────────────────────────────")
    for line in prompt.splitlines():
        print(f"  {line}")
    print("  ── end prompt ───────────────────────────────────────────────────")


def _print_outputs(trace: dict) -> None:
    _print_section("ORIGINAL OUTPUTS")
    raw = trace.get("raw_output")
    answer = trace.get("answer")
    print("  raw_output (un-stripped):")
    print(f"    {repr(raw) if raw is not None else '(none)'}")
    print()
    print(f"  answer (final, stripped):\n    {answer or '(none)'}")


def _do_replay(trace: dict) -> None:
    """Re-send the stored prompt to the original provider and compare with the original answer."""
    prompt = trace.get("prompt")
    if not prompt:
        print("\n  [Cannot replay — stored prompt is empty (request failed before prompt construction).]")
        return

    provider = trace.get("provider", "gemini")
    model_name = trace.get("model", "unknown")
    print(f"\n  Re-sending prompt to {provider}/{model_name} ...")

    try:
        if provider == "groq":
            raw_text = _replay_groq(prompt, model_name)
        else:
            raw_text = _replay_gemini(prompt, model_name)
    except Exception as exc:
        print(f"  [Replay failed: {exc}]")
        return

    replayed_answer = raw_text.strip()
    original_answer = trace.get("answer")

    _print_section("REPLAY OUTPUTS")
    print(f"  replayed answer:\n    {replayed_answer}")

    _print_section("MATCH COMPARISON")
    print(f"  original answer:\n    {original_answer}")
    print()
    if replayed_answer == original_answer:
        print("  >>> Outputs MATCH (exact).")
    else:
        print("  >>> Outputs DIFFER.")
        print("  This is EXPECTED: LLMs are non-deterministic. The same prompt")
        print("  can produce different token sequences across calls. The trace")
        print("  contains sufficient information to replay the request; exact")
        print("  output matching is not guaranteed without temperature=0 / seed.")


def _replay_gemini(prompt: str, model_name: str) -> str:
    import google.generativeai as genai
    from app.core.config import settings

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    return response.text


def _replay_groq(prompt: str, model_name: str) -> str:
    from groq import Groq
    from app.core.config import settings

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay a single stored RAG trace from traces/traces.jsonl.",
    )
    parser.add_argument(
        "--trace-id",
        required=True,
        help="The UUID trace_id to look up and replay.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        default=False,
        help="If set, re-run the Gemini call with the stored prompt.",
    )
    args = parser.parse_args()

    trace = load_trace(args.trace_id)
    if trace is None:
        print(f"error: no trace found with trace_id '{args.trace_id}'", file=sys.stderr)
        print(f"       check that 'traces/traces.jsonl' exists and the ID is correct.", file=sys.stderr)
        return 1

    _print_trace_info(trace)

    if trace.get("status") == "error":
        _print_section("ERROR DETAILS")
        error = trace.get("error", {})
        print(f"  type          : {error.get('type')}")
        print(f"  status_code   : {error.get('status_code')}")
        print(f"  detail        : {error.get('detail')}")
        print()
        print("  This trace represents a FAILED request. Replay is not meaningful")
        print("  because the LLM call was never made.")
        return 0

    _print_question(trace)
    _print_retrieved_chunks(trace)
    _print_prompt(trace)
    _print_outputs(trace)

    if args.replay:
        _do_replay(trace)
    else:
        print()
        print("  (Pass --replay to re-send the prompt to Gemini and compare outputs.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
