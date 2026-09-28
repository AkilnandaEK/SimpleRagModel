# -*- coding: ascii -*-
import ast, io, sys
from pathlib import Path
ROOT = Path(r"E:\week3")
LLM = ROOT / "benchmark" / "llm.py"
WF  = ROOT / "workflow" / "deterministic_workflow.py"

def dump_fn_returns(path, fn_name):
    src = io.open(str(path), encoding="utf-8", errors="replace").read()
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == fn_name:
            for sub in ast.walk(n):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Constant) and isinstance(sub.value.value, str):
                    seg = ast.get_source_segment(src, sub) or ""
                    print("FN", fn_name, "lines", sub.lineno, "-", sub.end_lineno)
                    print("SEG-ASCII", seg.encode("unicode_escape").decode("ascii"))
                    print("SEG-HAS-OBSERVATION", "observation" in seg)
                    print("SEG-HAS-EVIDENCE", "evidence" in seg)
    return None

print("===== benchmark/llm.py : _answer_from_observation =====")
dump_fn_returns(LLM, "_answer_from_observation")
print("===== workflow/deterministic_workflow.py : _step4_generate_answer =====")
dump_fn_returns(WF, "_step4_generate_answer")
print("===== DONE =====")