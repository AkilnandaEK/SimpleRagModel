# -*- coding: ascii -*-
"""
Permanently wire the proven grounded (extractive, evidence-quoting) offline
answer synthesizer into BOTH offline seams.

Why two seams
-------------
- benchmark/llm.py OfflineReasoner.decide finish branch -> _answer_from_observation
  (the ReAct agent output seam).
- workflow/deterministic_workflow.py _step4_generate_answer offline branch
  (the deterministic-workflow output seam).

Both currently return the SAME generic, evidence-free sentence, so the token-
overlap evaluator marks every scenario nearly-correct-becomes-incorrect even
though retrieval is healthy (fact sentence surfaces in top-5 for 10/12
scenarios).

The injectable grounding seam was already PROVEN at runtime: routing the finish
branch through eval/offline_answers.synthesize_grounded_answer lifted BOTH
agent and workflow to 90% (9/10). This script makes that binding permanent by
rewriting the two seam bodies in place, then verifying with compile + import +
a real self-test call into the SAME module the benchmark will import.
"""

from __future__ import annotations

import ast
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM_PATH = ROOT / "benchmark" / "llm.py"
WF_PATH = ROOT / "workflow" / "deterministic_workflow.py"
GEN_PATH = ROOT / "eval" / "offline_answers.py"

# --- grounded import that the seams will use (proven present & importable) ---
IMPORT_LINE = "from eval.offline_answers import synthesize_grounded_answer\n"


def anchor_from_ast(path: Path, fn_name: str, ret_has: str) -> str:
    """Extract the EXACT on-disk source text of the seam body via AST segment.

    The anchor is derived from the file's own AST so it ALWAYS matches whatever
    is on disk (get_source_segment returns the true bytes), immune to anchor
    spelling drift.
    """
    src = io.open(path, encoding="utf-8", errors="replace").read()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            fn = node
            break
    if fn is None:
        return None
    # find a Return node whose body/branch contains the tell-tale generic phrase
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Return) and ret_has in ast.get_source_segment(src, sub) or "":
            return ast.get_source_segment(src, sub)
    return None


def grounded_return(expr: str) -> str:
    return (
        "    try:\n"
        "        " + IMPORT_LINE +
        "    except Exception:\n"
        "        return REFUSAL_ANSWER\n"
        "    answer = synthesize_grounded_answer(question, " + expr + ")\n"
        "    if answer:\n"
        "        return answer\n"
        "    return REFUSAL_ANSWER\n"
    )


def patch_seam(path: Path, fn_name: str, expr: str, label: str) -> bool:
    src = io.open(path, encoding="utf-8", errors="replace").read()
    old = anchor_from_ast(path, fn_name, "the exact \"parameter and default values\".")
    if not old or old not in src:
        print(f"[skip:{label}] could not locate seam anchor on disk; file left unchanged")
        return False
    new = grounded_return(expr)
    if src.count(old) != 1:
        print(f"[skip:{label}] anchor count != 1; file left unchanged")
        return False
    out = src.replace(old, new, 1)
    compile(out, str(path), "exec")  # gate before touching disk
    path.write_text(out, encoding="utf-8")
    print(f"[ok:{label}] seam rewired -> grounded synthesizer (1 anchor swapped)")
    return True


def ensure_import(path: Path, label: str) -> bool:
    src = io.open(path, encoding="utf-8", errors="replace").read()
    if IMPORT_LINE in src:
        return True  # already present from a previous run
    marker = "from safety.circuit_breaker import CircuitBreaker\n"
    if marker in src and src.count(marker) == 1:
        src = src.replace(marker, marker + IMPORT_LINE, 1)
    else:
        # fallback: append after the first top-level import
        lines = src.splitlines(keepends=True)
        for i, ln in enumerate(lines):
            if ln.startswith("import ") or ln.startswith("from "):
                insert_at = i + 1
                break
        lines.insert(insert_at, IMPORT_LINE)
        src = "".join(lines)
    compile(src, str(path), "exec")
    path.write_text(src, encoding="utf-8")
    print(f"[ok:{label}] grounded import present")
    return True


for p, bak in ((LLM_PATH, "llm_offline_bak"), (WF_PATH, "wf_offline_bak")):
    b = ROOT / "scripts" / (bak + ".py")
    if not b.exists():
        shutil.copy2(p, b)
        print(f"[bak:{bak}] saved")

ok = True
ok &= patch_seam(LLM_PATH, "_answer_from_observation",
                 '[{"text": observation}]', "agent.llm._answer_from_observation")
ok &= patch_seam(WF_PATH, "_step4_generate_answer",
                 "evidence", "workflow._step4_generate_answer")

print("[import wiring] ensure both files can import the synthesizer...")
ok &= ensure_import(LLM_PATH, "agent.llm.import")
ok &= ensure_import(WF_PATH,  "workflow.import")

# Verify
sys.path.insert(0, str(ROOT))
try:
    import eval.offline_answers as m
    synth = getattr(m, "synthesize_grounded_answer")
    sample = synth(
        "What is the default value for mode when rendering a Markdown document?",
        [{"text": "The default value for mode is 'markdown', which renders the document server-side."}],
    )
    print("[self-test] synthesize_grounded_answer ->", repr(sample))
except Exception as e:
    print("[FAIL:self-test]", type(e).__name__, str(e)[:140])
    ok = False

for p in (LLM_PATH, WF_PATH, GEN_PATH):
    try:
        import py_compile
        py_compile.compile(str(p), doraise=True)
        print(f"[compile-ok] {p.name}")
    except Exception as e:
        print(f"[compile-FAIL] {p.name}: {e}")
        ok = False

print("ALL_GROUNDED_OK" if ok else "PATCH_INCOMPLETE")