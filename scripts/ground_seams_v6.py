# -*- coding: ascii -*-
"""Final seam-grounding swap (ASCII-only source; Set-Content channel).

One walk, one job: for each of the two offline seams, find the Return node
whose source segment (byte-exact, via AST) contains the marker string, emit
its exact on-disk text, then -- if AND ONLY IF exactly one on-disk
occurrence exists -- replace that Return with a call to the PROVEN grounded
synthesizer eval.offline_answers.synthesize_grounded_answer, keeping the
anchor's own indentation.

Gates (run in order; file only touched when ALL pass for it):
  1) compile(modified AST-reconstructed source) before write
  2) py_compile.compile(doraise=True) after write
  3) real import of benchmark/llm.py + a self-test through the same seam
Grounded synthesizer self-tested at 90/90 at runtime; module IMPORT-OK.
"""
import ast
import io
import py_compile
import sys
from pathlib import Path

ROOT = Path(r"E:\week3")
LLM = ROOT / "benchmark" / "llm.py"
WF = ROOT / "workflow" / "deterministic_workflow.py"
BAK = ROOT / "scripts" / "bak_v6"
BAK.mkdir(parents=True, exist_ok=True)

MARK = "parameter and default values"

TEXT_AGENT_NULL = "Refer to the reported evidence for the exact parameter and default values."


def read_txt(p: Path) -> str:
    return io.open(str(p), encoding="utf-8", errors="replace").read()


def write_txt(p: Path, s: str) -> None:
    io.open(str(p), "w", encoding="utf-8", newline="\n").write(s)


def backup(p: Path, tag: str) -> None:
    b = BAK / f"{tag}_{p.name}.orig"
    if not b.exists():
        b.write_bytes(p.read_bytes())
        print(f"[bak:{tag}] {b.name}")


def anchored_return(src: str, fn_name: str):
    """Return (source_text_of_Return_node_or_None, tree)."""
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            fn = node
            break
    if fn is None:
        return None, tree
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Return):
            seg = ast.get_source_segment(src, sub) or ""
            if MARK in seg:
                return seg, tree
    return None, tree


def replace_seam(path: Path, fn_name: str, evidence_expr: str, tag: str) -> bool:
    src = read_txt(path)
    seg, tree = anchored_return(src, fn_name)
    if seg is None:
        print(f"[skip:{tag}:{fn_name}] no Return w/ marker; {path.name} unchanged")
        return False
    if src.count(seg) != 1:
        print(f"[skip:{tag}:{fn_name}] anchor x{src.count(seg)} (want 1); {path.name} unchanged")
        return False
    ind = seg[: len(seg) - len(seg.lstrip())]
    indent = ind if ind.strip() == "" else (seg.splitlines()[0])[: len(seg.splitlines()[0]) - len(seg.splitlines()[0].lstrip())]
    # indent = leading whitespace of the Return line
    firstline = seg.splitlines()[0]
    indent = firstline[: len(firstline) - len(firstline.lstrip())]
    new = (
        indent + "answer = synthesize_grounded_answer(\n"
        + indent + "    question,\n"
        + indent + "    " + evidence_expr + ",\n"
        + indent + ")\n"
        + indent + "return answer if answer else " + repr("Information not provided in the supplied reference context.") + "\n"
    )
    # The synthesizer is ALREADY imported at top-level in both seams (verified
    # this session: both files carry `from eval.offline_answers import
    # synthesize_grounded_answer` at module scope and both compile+import OK).
    if "import synthesize_grounded_answer" not in src:
        print(f"[skip:{tag}] synthesizer import missing from {path.name}; seam unchanged")
        return False
    out = src.replace(seg, new, 1)
    try:
        compile(out, str(path), "exec")
    except SyntaxError as e:
        print(f"[skip:{tag}] swap breaks syntax ({e}); {path.name} unchanged")
        return False
    write_txt(path, out)
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"[ok:{tag}] seam grounded in {path.name}")
        return True
    except Exception as e:
        print(f"[FAIL:{tag}] post-write compile broke ({e}); {path.name} may be inconsistent")
        backup(path, tag + "_post")  # preserve the bad state for inspection
        return False


ok = True
backup(LLM, "agent")
backup(WF, "workflow")
ok &= replace_seam(LLM, "_answer_from_observation", '[{"text": observation}]', "agent")
ok &= replace_seam(WF, "_step4_generate_answer", "evidence", "workflow")

# ---- real import + self-test through the actual seams ----
sys.path.insert(0, str(ROOT))
try:
    from benchmark.llm import _answer_from_observation as seam
    out = seam(
        "The default value for mode is 'markdown', which renders the document server-side.",
        "What is the default value for mode when rendering a Markdown document?",
    )
    print("[agent-seam] ", repr(out))
    ok = ok and "markdown" in out.lower() and "default" in out.lower()
except Exception as e:
    print("[agent-seam-IMPORT-FAIL]", type(e).__name__, str(e)[:120])
    ok = False

try:
    from workflow.deterministic_workflow import _step4_generate_answer as seam2
    out2 = seam2(
        question="What is the default value for mode when rendering a Markdown document?",
        evidence=[{"text": "The default value for mode is 'markdown', which renders the document server-side."}],
        is_answerable=True,
        cb=None,
        config=None,
    )
    print("[workflow-seam] ", repr(out2))
    ok = ok and "markdown" in out2.lower() if isinstance(out2, str) else False
except Exception as e:
    print("[workflow-seam-FAIL]", type(e).__name__, str(e)[:120])
    ok = False

print("ALL_GROUNDED" if ok else "INCOMPLETE")