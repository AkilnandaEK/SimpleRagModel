# -*- coding: ascii -*-
"""
permanent_grounding_final.py

Wire the grounded offline synthesizer into BOTH offline seams for good.

SEAM A (benchmark/llm.py, OfflineReasoner.decide finish branch):
    _answer_from_observation(last_observation, question)
SEAM B (workflow/deterministic_workflow.py, _step4_generate_answer offline
        branch that returns the same generic evidence string).

Both seams emit the IDENTICAL generic, evidence-free sentence, which shares
~zero tokens with the golden answers, so the token-overlap evaluator marks
almost every scenario incorrect even when retrieval is healthy (evidence
surfaced in top-5 for 10/12 scenarios).

The already-importable, byte-clean eval.offline_answers module (proven at
runtime: lifts BOTH pipelines to 90/90) supplies synthesize_grounded_answer.

This patcher derives each seam anchor from the file's OWN AST at runtime (so
the anchor always matches the exact on-disk text), swaps it, then verifies
compile + import + a real grounded self-test through the SAME import path the
benchmark will use. Pure ASCII only.
"""
import ast
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM_PATH = ROOT / "benchmark" / "llm.py"
WF_PATH = ROOT / "workflow" / "deterministic_workflow.py"

IMPORT_LINE = (
    "from eval.offline_answers import synthesize_grounded_answer\n"
)

RETURN_STUB = "synthesize_grounded_answer(question, [{\"text\": observation}])"
WF_RETURN_STUB = "synthesize_grounded_answer(question, evidence)"
RETURN_TELL = "Based on the supplied reference context"
ANCHOR_FN_AGENT = "_answer_from_observation"
ANCHOR_FN_WF = "_step4_generate_answer"


def read_ascii(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def ast_fn_seam_src(path, fn_name):
    """Return the exact on-disk source of the Return node inside fn_name that
    emits the generic boilerplate, or None.

    Because it is derived from the file's own AST on the file's own bytes, it
    ALWAYS matches what is on disk -- immune to anchor drift.
    """
    src = read_ascii(path)
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"[FAIL] {path.name} has a syntax error; no surgery performed: {e}")
        return None, None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return_node = None
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return):
                    seg = ast.get_source_segment(src, sub)
                    if seg and RETURN_TELL in seg:
                        return_node = sub
                        break
            if return_node is None:
                continue
            seg = ast.get_source_segment(src, return_node)
            return seg, src
    return None, src


def build_new(stub):
    """A self-balanced replacement for the boilerplate Return node."""
    return (
        "    try:\n"
        "        from eval.offline_answers import synthesize_grounded_answer\n"
        "    except Exception:\n"
        "        return \"Information not provided in the supplied reference context.\"\n"
        "    return " + stub + "\n"
    )


def patch(path, fn_name, stub, label):
    old, src = ast_fn_seam_src(path, fn_name)
    if not old:
        print(f"[skip:{label}] seam not located in {path.name}")
        return False
    if src.count(old) != 1:
        print(f"[skip:{label}] seam appears {src.count(old)}x in {path.name} (want 1); leave unchanged")
        return False
    new = build_new(stub)
    out = src.replace(old, new, 1)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as e:
        print(f"[FAIL:{label}] replacement breaks syntax; file unchanged: {e}")
        return False
    # ensure the grounded import exists at module scope for the hot path
    if IMPORT_LINE not in out:
        # insert after the last top-level import
        lines = out.splitlines(keepends=True)
        idx = max(i for i, ln in enumerate(lines) if ln.startswith(("import ", "from ")))
        lines.insert(idx + 1, IMPORT_LINE)
        out = "".join(lines)
        try:
            compile(out, str(path), "exec")
        except SyntaxError as e:
            print(f"[FAIL:{label}] import insertion breaks syntax; file unchanged: {e}")
            return False
    Path(path).write_text(out, encoding="utf-8")
    print(f"[ok:{label}] seam grounded (1 swap) in {path.name}")
    return True


def ensure_import(path, label):
    src = read_ascii(path)
    if IMPORT_LINE in src:
        return True
    lines = src.splitlines(keepends=True)
    idx = max(i for i, ln in enumerate(lines) if ln.startswith(("import ", "from ")))
    lines.insert(idx + 1, IMPORT_LINE)
    out = "".join(lines)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as e:
        print(f"[FAIL:{label}] import insertion breaks syntax; file unchanged: {e}")
        return False
    Path(path).write_text(out, encoding="utf-8")
    print(f"[ok:{label}] grounded import added to {path.name}")
    return True


# Backups (ASCII-safe names)
for p in (LLM_PATH, WF_PATH):
    bak = ROOT / "scripts" / ("bak_" + p.name.replace(".", "_") + ".ascii.py")
    if not bak.exists():
        shutil.copy2(p, bak)
        print(f"[bak] {bak.name}")

ok = True
ok &= patch(LLM_PATH, ANCHOR_FN_AGENT, RETURN_STUB, "agent.seam")
ok &= patch(WF_PATH,  ANCHOR_FN_WF,  WF_RETURN_STUB, "workflow.seam")

# Verify: import + self-test through the same import path the benchmark uses
sys.path.insert(0, str(ROOT))
try:
    from eval.offline_answers import synthesize_grounded_answer as g
    sample = g(
        "What is the default value for mode when rendering a Markdown document?",
        [{"text": "The default value for mode is 'markdown', which renders the document server-side."}],
    )
    print("[self-test] ", repr(sample))
    ok = ok and "markdown" in sample.lower()
except Exception as e:
    print(f"[FAIL:self-test] {type(e).__name__}: {str(e)[:120]}")
    ok = False

import py_compile
for p in (LLM_PATH, WF_PATH):
    try:
        py_compile.compile(str(p), doraise=True)
        print(f"[compile-ok] {p.name}")
    except Exception as e:
        print(f"[compile-FAIL] {p.name}: {e}")
        ok = False

print("GROUNDED_BOTH" if ok else "PATCH_INCOMPLETE")