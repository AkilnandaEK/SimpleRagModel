# -*- coding: ascii -*-
"""Apply grounded answers at BOTH offline seams, anchors derived from each
file's OWN AST at runtime (byte-exact via ast.get_source_segment, no
hand-written anchor that could drift). Pure ASCII. Idempotent. Safe:
any mismatch -> file left untouched; backups taken first."""
import ast
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM = ROOT / "benchmark" / "llm.py"
WF = ROOT / "workflow" / "deterministic_workflow.py"

SYN = "eval.offline_answers"
FN = "synthesize_grounded_answer"

IMPORT_STMT = "from " + SYN + " import " + FN + "\n"


def read_text(p: Path) -> str:
    return io.open(str(p), encoding="utf-8", errors="replace").read()


def write_text(p: Path, s: str) -> None:
    io.open(str(p), "w", encoding="utf-8", newline="\n").write(s)


def backup(p: Path, tag: str) -> None:
    d = ROOT / "scripts" / "baks"
    d.mkdir(parents=True, exist_ok=True)
    b = d / (tag + "_" + p.name)
    if not b.exists():
        shutil.copy2(p, b)
        st.write(f"[bak:{tag}] {b.name}")


ok = True


def grounded_call(question_arg: str, evidence_arg: str, indent: str) -> str:
    nl = "\n"
    return (
        indent + "try:" + nl
        + indent + "    " + IMPORT_STMT
        + indent + "except Exception:" + nl
        + indent + "    return " + repr(REFUSAL) + nl
        + indent + "answer = " + FN + "(question, " + evidence_arg + ")" + nl
        + indent + "return answer if answer else " + repr(REFUSAL) + nl
    )


# -------- Seam 1: benchmark/llm.py  _answer_from_observation --------
def patch_llm() -> bool:
    src = read_text(LLM)
    tree = ast.parse(src)
    seg_fn = "_answer_from_observation"
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == seg_fn:
            target = node
            break
    if target is None:
        print("[skip:llm._answer_from_observation] not found; file unchanged")
        return False
    # find the generic return statement inside it (the seam)
    old = None
    for node in ast.walk(target):
        if isinstance(node, ast.Return):
            seg = ast.get_source_segment(src, node) or ""
            if "Refer to the reported evidence for the exact" in seg:
                old = seg
                break
    if old is None:
        print("[skip:llm.return] generic return anchor not found; file unchanged")
        return False
    if src.count(old) != 1:
        print(f"[skip:llm.return] anchor x{src.count(old)} (want 1); file unchanged")
        return False
    new = grounded_call("question", '[{"text": observation}]', "        ")
    # observation is a single string in the agent seam: wrap as one evidence item
    new = grounded_call("question", '[{"text": observation}]', "        ")
    out = src.replace(old, new, 1)
    try:
        compile(out, str(LLM), "exec")
    except SyntaxError as e:
        print("[skip:llm] replacement breaks syntax; file unchanged:", e)
        return False
    write_text(LLM, out)
    print("[ok:llm] _answer_from_observation now grounded")
    return True


# -------- Seam 2: workflow/deterministic_workflow.py  _step4_generate_answer --------
def patch_wf() -> bool:
    src = read_text(WF)
    tree = ast.parse(src)
    seg_fn = "_step4_generate_answer"
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == seg_fn:
            target = node
            break
    if target is None:
        print("[skip:wf._step4_generate_answer] not found; file unchanged")
        return False
    old = None
    for node in ast.walk(target):
        if isinstance(node, ast.Return):
            seg = ast.get_source_segment(src, node) or ""
            if "Refer to the reported evidence for the exact" in seg:
                old = seg
                break
    if old is None:
        print("[skip:wf.return] generic return anchor not found; file unchanged")
        return False
    if src.count(old) != 1:
        print(f"[skip:wf.return] anchor x{src.count(old)} (want 1); file unchanged")
        return False
    new = grounded_call("question", "evidence", "            ")
    out = src.replace(old, new, 1)
    try:
        compile(out, str(WF), "exec")
    except SyntaxError as e:
        print("[skip:wf] replacement breaks syntax; file unchanged:", e)
        return False
    write_text(WF, out)
    print("[ok:wf] _step4_generate_answer now grounded")
    return True


# -------- Import wiring (idempotent) --------
def ensure_import(p: Path, tag: str) -> bool:
    src = read_text(p)
    if IMPORT_STMT in src:
        print(f"[ok:{tag}] import already present")
        return True
    lines = src.splitlines(keepends=True)
    # insert after the last top-level import/from line
    anchor = -1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith(("import ", "from ")) and not ln.startswith((" ", "\t")):
            anchor = i
    if anchor == -1:
        print(f"[skip:{tag}] no import block; file unchanged")
        return False
    lines.insert(anchor + 1, IMPORT_STMT)
    out = "".join(lines)
    try:
        compile(out, str(p), "exec")
    except SyntaxError as e:
        print(f"[skip:{tag}] import insert breaks syntax; file unchanged: {e}")
        return False
    write_text(p, out)
    print(f"[ok:{tag}] import added")
    return True


for p, tag in ((LLM, "llm"), (WF, "wf")):
    backup(p, tag)

if not patch_llm():
    ok = False
if not patch_wf():
    ok = False
ok = ensure_import(LLM, "llm.import") and ok
ok = ensure_import(WF, "wf.import") and ok

# -------- Self-verify: compile + import + self-test throughput the real seam --------
sys.path.insert(0, str(ROOT))
try:
    from eval import offline_answers
    import benchmark.llm, workflow.deterministic_workflow
    q = "What is the default value for mode when rendering a Markdown document?"
    obs = "The default value for mode is 'markdown', which renders the document server-side."
    ans = benchmark.llm._answer_from_observation(obs, q)
    arc = "markdown" in ans.lower() and "default" in ans.lower()
    print("[self-test:agent-seam]", repr(ans), "grounded=" , arc)
    if not arc:
        ok = False
    import py_compile
    for p in (LLM, WF):
        py_compile.compile(str(p), doraise=True)
        print("[compile-ok]", p.name)
except Exception as e:
    print("[self-test-FAIL]", type(e).__name__, str(e)[:140])
    ok = False

print("GROUNDING_APPLIED" if ok else "INCOMPLETE (safe; files unmodified where anchors failed)")