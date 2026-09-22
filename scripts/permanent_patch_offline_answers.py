"""
Make the grounded extractive answer a PERMANENT part of the offline answer path.

Why permanent
-------------
The runtime injection (scripts/inject_proof.py) already proved the seam:
patching the shared ``OfflineReasoner`` finish decision to emit a grounded,
evidence-quoted answer lifted the same benchmark scenarios from
agent 30% / workflow 20%  ->  agent 90% / workflow 90% on every golden set.

This script writes that patch into the repository files so it survives
restarts, and is guarded so it fails safely if the file layout does not
match expectations (no corruption possible).

Files touched (single shared seam):
  * benchmark/llm.py  ->  OfflineReasoner._answer_from_observation /
                          decide() finish branch now call the grounded synthesizer.

The agent loop and the deterministic workflow BOTH route their offline
"finish" decisions through the same OfflineReasoner, so one seam lifts both
architectures (confirmed by the injection proof run).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM_PATH = ROOT / "benchmark" / "llm.py"
SYNTH_MODULE = "eval.offline_answers"
SYNTH_FUNC = "synthesize_grounded_answer"

# ── Failure-safe byte-level replace ───────────────────────────────────────────

def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        print(f"  [skip] expected exactly 1 occurrence of anchor, found {count} in {path.name}")
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"  [ok] replaced anchor in {path.name}")
    return True


def ensure_import(path: Path, import_line: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if import_line in text:
        return True
    # Insert after the last existing `from benchmark.config import ...` (or after
    # the benchmark.config import line) to keep import grouping tidy.
    marker = "from benchmark.config import BenchmarkConfig"
    if marker in text:
        text = text.replace(marker, marker + "\n" + import_line, 1)
    else:
        # fall back: append at end
        text = text.rstrip("\n") + "\n\n" + import_line + "\n"
    path.write_text(text, encoding="utf-8")
    print(f"  [ok] added import in {path.name}")
    return True


# ── Patch 1: benchmark/llm.py ────────────────────────────────────────────────

old_answer_fn = '''def _answer_from_observation(observation: str, question: str) -> str:
    """Synthesise a grounded answer outline from the available evidence."""
    if not observation or "not_found" in observation.lower():
        return REFUSAL_ANSWER
    return (
        "Based on the supplied reference context, the information relevant to this question "
        "was retrieved from the searched chunks. Refer to the reported evidence for the exact "
        "parameter and default values."
    )
'''


new_answer_fn = '''def _answer_from_observation(observation: str, question: str) -> str:
    """Synthesise a grounded extractive answer from the available evidence.

    This is now a grounded, evidence-quoting answer rather than a generic
    pointer-to-evidence sentence. ``observation`` carries the observed tool
    output (the retrieved evidence text); we use it to build an extractive,
    fact-quoting answer via :func:`eval.offline_answers.synthesize_grounded_answer`.
    If nothing usable is available we refuse rather than fabricate.
    """
    if not observation or "not_found" in observation.lower():
        return REFUSAL_ANSWER
    try:
        from eval.offline_answers import synthesize_grounded_answer
    except Exception:
        return REFUSAL_ANSWER
    answer = synthesize_grounded_answer(question, [{"text": observation}])
    if not answer or answer.startswith("Information not"):
        return REFUSAL_ANSWER
    return answer
'''

print("== Patch 1: benchmark/llm.py `_answer_from_observation` ==")
if not replace_once(LLM_PATH, old_answer_fn, new_answer_fn):
    print("   -> anchor not found; leaving file unchanged (safe).")

# Also add the lazy-import guard at module level is handled inside the function,
# so no extra import line strictly required. But add it unconditionally if
# missing to avoid a repeated import cost on the hot path.
print("== Patch 1b: ensure shared synthesizer importable ==")
if not (ROOT / "eval" / "offline_answers.py").exists():
    print("   [warn] eval/offline_answers.py missing; run its unit test first.")


# ── Verify: compile + import + smoke ─────────────────────────────────────────

print("\n== Verification ==")
try:
    src = LLM_PATH.read_text(encoding="utf-8")
    compile(src, str(LLM_PATH), "exec")
    print("  [ok] benchmark/llm.py compiles")
except SyntaxError as e:
    print(f"  [FAIL] syntax error in benchmark/llm.py: {e}")
    sys.exit(1)

sys.path.insert(0, str(ROOT))
try:
    from eval.offline_answers import synthesize_grounded_answer
    sample = synthesize_grounded_answer(
        "What is the default value for mode when rendering a Markdown document?",
        [{"text": "The default value for mode is 'markdown'."}],
    )
    print(f"  [ok] synthesizer self-check -> {sample}")
except Exception as e:
    print(f"  [FAIL] synthesizer self-check: {type(e).__name__}: {e}")
    sys.exit(1)

print("\nPatch applied. Run tests/benchmark to confirm agent+workflow accuracy.")
