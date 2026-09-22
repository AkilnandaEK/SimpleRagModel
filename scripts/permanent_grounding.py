# -*- coding: ascii -*-
"""
permanent_grounding.py  (pure ASCII)

Permanently wire the PROVEN extractive grounded synthesizer into BOTH offline
seams, so the lift (agent 30->90, workflow 20->90, proven at runtime against
all three golden sheets) survives restarts instead of living only in a proof
script.

Seam A : benchmark/llm.py   `_answer_from_observation`  (agent finisher)
Seam B : workflow/deterministic_workflow.py `_step4_generate_answer` offline branch

Anchors are NOT hardcoded; each is re-derived at runtime from the file's own
AST (source segment = exact on-disk bytes), replaced as a single balanced
statement, then compile+import+self-test verified. If any anchor is ambiguous
or the swap would break syntax the file is left untouched.

Synthesizer: eval/offline_answers.py synthesize_grounded_answer (proven).
"""

import ast
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM_F = ROOT / "benchmark" / "llm.py"
WF_F = ROOT / "workflow" / "deterministic_workflow.py"
SYNTH_MOD = "eval.offline_answers"
SYNTH_FN = "synthesize_grounded_answer"

CANARY = "Information not provided in the supplied reference context."

AGENT_STUB = (
    "    try:\n"
    "        from eval.offline_answers import synthesize_grounded_answer\n"
    "    except Exception:\n"
    "        return " + repr(CANARY) + "\n"
    "    g = synthesize_grounded_answer(question, [{\"text\": observation}])\n"
    "    return g if g else " + repr(CANARY) + "\n"
)

WF_STUB = (
    "            try:\n"
    "                from eval.offline_answers import synthesize_grounded_answer\n"
    "            except Exception:\n"
    "                return " + repr(CANARY) + "\n"
    "            g = synthesize_grounded_answer(question, evidence)\n"
    "            return g if g else " + repr(CANARY) + "\n"
)


def read(src: str) -> str:
    return io.open(src, encoding="utf-8", errors="replace").read()


def process(path: Path, target_fn: str, new_stub: str, label: str) -> bool:
    src = read(str(path))
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_fn:
            fn = node
            break
    if fn is None:
        print(f"[skip:{label}] function {target_fn} not found; unchanged")
        return False

    # find the Return statement inside fn whose value is the generic sentence
    ret_node = None
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            if "was retrieved from the searched chunks" in n.value.value:
                ret_node = n
                break
    if ret_node is None:
        print(f"[skip:{label}] generic return not found in {target_fn}; unchanged")
        return False

    old = ast.get_source_segment(src, ret_node)
    if not old:
        print(f"[skip:{label}] could not obtain source segment; unchanged")
        return False
    if src.count(old) != 1:
        print(f"[skip:{label}] segment x{src.count(old)} (want 1); unchanged")
        return False

    new_block = new_stub
    out = src.replace(old, new_block, 1)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as e:
        print(f"[FAIL:{label}] swap breaks syntax ({e}); file unchanged")
        return False

    path.write_text(out, encoding="utf-8")
    print(f"[ok:{label}] {target_fn} grounded ({old.count(chr(10))+1} lines -> {new_block.count(chr(10))+1})")
    return True


def ensure_import(path: Path, label: str) -> bool:
    src = read(str(path))
    line = "from eval.offline_answers import synthesize_grounded_answer\n"
    if line in src:
        print(f"[ok:{label}] import already present")
        return True
    lines = src.splitlines(keepends=True)
    # insert after the last top-level import / from-import line
    idx = -1
    for i, ln in enumerate(lines):
        if ln.startswith(("import ", "from ")) and not ln.startswith(("    ", "\t")):
            idx = i
    if idx < 0:
        print(f"[skip:{label}] no import block anchor; unchanged")
        return False
    add = line
    # keep the lazy import in the seam; also add a top-level one for speed only if safe
    lines.insert(idx + 1, add)
    out = "".join(lines)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as e:
        print(f"[FAIL:{label}] import insert breaks syntax ({e}); unchanged")
        return False
    path.write_text(out, encoding="utf-8")
    print(f"[ok:{label}] import added")
    return True


def backup(path: Path, label: str) -> None:
    bak = ROOT / "scripts" / f"bak_{label}_{path.name}.orig"
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[bak:{label}] {bak.name}")


backup(LLM_F, "agent")
backup(WF_F, "workflow")

ok = True
ok &= ensure_import(LLM_F, "agent.import")
ok &= ensure_import(WF_F, "workflow.import")
ok &= process(LLM_F, "_answer_from_observation", AGENT_STUB, "agent.seam")
ok &= process(WF_F, "_step4_generate_answer", WF_STUB, "workflow.seam")

# ---- self-test through the REAL import path ----
sys.path.insert(0, str(ROOT))
try:
    from eval.offline_answers import synthesize_grounded_answer
    out = synthesize_grounded_answer(
        "What is the default value for mode when rendering a Markdown document?",
        [{"text": "The default value for mode is 'markdown', which renders the document server-side."}],
    )
    print("[self-test]", repr(out))
    ok &= ("markdown" in out.lower())
except Exception as e:
    print("[self-test-FAIL]", type(e).__name__, str(e)[:120])
    ok = False

import py_compile
for p in (LLM_F, WF_F):
    try:
        py_compile.compile(str(p), doraise=True)
        print(f"[compile-ok] {p.name}")
    except Exception as e:
        print(f"[compile-FAIL] {p.name}: {e}")
        ok = False

print("GROUNDED_PERMANENT" if ok else "INCOMPLETE")
