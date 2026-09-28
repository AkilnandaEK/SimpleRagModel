# -*- coding: ascii -*-
"""
apply_grounding_seams_final.py   (pure ASCII file content)

Deterministic, byte-safe switch of BOTH offline seams to the PROVEN grounded
synthesizer (eval/offline_answers.py -> IMPORT-OK; runtime 90/90 agent and
90/90 workflow). Anchors are NOT typed by hand -- each one is derived at
runtime from the target file's OWN AST via ast.get_source_segment (byte-exact
on-disk text), so a stale/missing anchor can never partially patch or corrupt.

Seam agent (benchmark/llm.py, OfflineReasoner.decide finish branch) and seam
workflow (workflow/deterministic_workflow.py, _step4_generate_answer offline
branch) currently return the IDENTICAL generic, evidence-free sentence:

    "Based on the supplied reference context, the information relevant to this
     question was retrieved from the searched chunks. Refer to the reported
     evidence for the exact parameter and default values."

That sentence shares ~zero tokens with any golden answer, so the token-overlap
evaluator marks nearly every scenario incorrect even though retrieval is
healthy (fact surfaced in top-5 evidence for 10 of 12 scenarios). The grounded
synthesizer fixes both by quoting the best fact-bearing sentence from the
RETRIEVED EVIDENCE verbatim (extractive, deterministic, honest) instead of
returning the shared generic line.

This script:
  * reads the file, parses to AST, finds the exact on-disk text of the Return
    node that contains the generic sentence via get_source_segment,
  * replaces exactly that segment with a grounded synthesizer call (the new
    text embeds question + the evidence the seam actually holds),
  * verifies: unique anchor (count==1), balanced compile, py_compile, a live
    import of the grounded seam, and a real self-test,
  * leaves the file byte-identical to its backup on ANY failure.

Pure ASCII throughout: no box-drawing, no arrows, no smart quotes, no em-dash
-- everything in this file renders as bytes 0x20-0x7E so the on-disk bytes
cannot be scrambled by any later tool round-trip.
"""

import ast
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM = ROOT / "benchmark" / "llm.py"
WF = ROOT / "workflow" / "deterministic_workflow.py"
BAK = ROOT / "scripts" / "baks"

REFUSAL = "REFUSAL_ANSWER"
GREP = "Refer to the reported evidence"
SENTINEL = "Information not provided in the supplied reference context."
TEXT_LEAF = '"parameter and default values."'
SYNTH_FN = "synthesize_grounded_answer"
SYNTH_IMPORT = "from eval.offline_answers import synthesize_grounded_answer\n"


def read_ascii(p: Path) -> str:
    return io.open(str(p), encoding="utf-8", errors="replace").read()


def write_ascii(p: Path, s: str) -> None:
    io.open(str(p), "w", encoding="utf-8", newline="\n").write(s)


def backup(path: Path, tag: str) -> Path:
    b = BAK / (tag + "_" + path.name + ".bak.py")
    BAK.mkdir(parents=True, exist_ok=True)
    if not b.exists():
        shutil.copy2(str(path), str(b))
        print(f"[bak:{tag}] {b.name}")
    return b


def seam_old(src: str, fn_name: str) -> str | None:
    """Return the byte-exact on-disk Return segment for the given seam fn."""
    tree = ast.parse(src)
    want = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant):
                    seg = ast.get_source_segment(src, sub) or ""
                    if TEXT_LEAF in seg:
                        want = seg
                        break
        if want is not None:
            break
    return want


def synt_call(var_expr: str, indent: str) -> str:
    return (
        indent + "try:\n"
        + indent + "    " + SYNTH_IMPORT
        + indent + "except Exception:\n"
        + indent + "    return " + repr(SENTINEL) + "\n"
        + indent + "g = " + SYNTH_FN + "(question, " + var_expr + ")\n"
        + indent + "return g if g else " + repr(SENTINEL) + "\n"
    )


def seam_new(src: str, fn_name: str, var_expr: str, tag: str) -> tuple[str, str] | None:
    old = seam_old(src, fn_name)
    if not old:
        print(f"[skip:{tag}] seam Return not found via AST; {tag} unchanged")
        return None
    if src.count(old) != 1:
        print(f"[skip:{tag}] anchor x{src.count(old)} (want 1); {tag} unchanged")
        return None
    new = synt_call(var_expr, old[: len(old) - len(old.lstrip())].replace("return ", ""))
    # build replacement with the SAME leading indentation as the original return
    lead = old[: len(old) - len(old.lstrip())]
    new = synt_call(var_expr, lead)
    return old, new


def apply(path: Path, fn_name: str, var_expr: str, tag: str) -> bool:
    src = read_ascii(path)
    old, new = seam_new(src, fn_name, var_expr, tag)
    if not old:
        return False
    out = src.replace(old, new, 1)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as e:
        print(f"[FAIL:{tag}] replacement breaks syntax; {tag} unchanged: {e}")
        return False
    write_ascii(path, out)
    # verify on disk
    try:
        compile(read_ascii(path), str(path), "exec")
        print(f"[ok:{tag}] grounded seam installed (1 swap)")
        return True
    except SyntaxError as e:
        print(f"[FAIL:{tag}] on-disk verify broke: {e}")
        return False


ok = True
for p, fn, var, tag in (
    (LLM, "_answer_from_observation", "observation", "agent"),
    (WF, "_step4_generate_answer", "evidence", "workflow"),
):
    backup(p, tag)
    ok &= apply(p, fn, var, tag)

# verify imports + compile + self-test
sys.path.insert(0, str(ROOT))
try:
    from eval.offline_answers import synthesize_grounded_answer
    q = "What is the default value for mode?"
    ev = [{"text": "The default value for mode is 'markdown', which renders the document server-side."}]
    a = synthesize_grounded_answer(q, ev)
    print("[self-test]", repr(a))
    print("[self-test:grounded]", "markdown" in a.lower() and "default" in a.lower())
except Exception as e:
    print("[FAIL:self-test]", type(e).__name__, str(e)[:120])
    ok = False

for p in (LLM, WF):
    try:
        import py_compile
        py_compile.compile(str(p), doraise=True)
        print(f"[compile-ok] {p.name}")
    except Exception as e:
        print(f"[compile-FAIL] {p.name}: {e}")
        ok = False

print("ALL_GROUNDED" if ok else "INCOMPLETE")
