# -*- coding: ascii -*-
import ast, io, sys
from pathlib import Path
ROOT=Path(r"E:\week3")
for p,tag,fn in ((ROOT/"benchmark"/"llm.py","agent","_answer_from_observation"),
                 (ROOT/"workflow"/"deterministic_workflow.py","workflow","_step4_generate_answer")):
    src=io.open(str(p),encoding="utf-8",errors="replace").read()
    try:
        tree=ast.parse(src)
        seg=None; ind=0
        for n in ast.walk(tree):
            if isinstance(n,ast.FunctionDef) and n.name==fn:
                for sub in ast.walk(n):
                    if isinstance(sub,ast.Return):
                        s=ast.get_source_segment(src,sub) or ""
                        if "parameter and default values" in s:
                            seg=s; ind=sub.col_offset; break
            if seg: break
        print(f"[TRUTH:{tag}] fn={fn} seam-fn-present={any(isinstance(n,ast.FunctionDef) and n.name==fn for n in ast.walk(tree))}")
        print(f"[TRUTH:{tag}] anchor-return-found={seg is not None} col={ind}")
        if seg:
            # is the seam STILL the generic sentence, or already grounded?
            print(f"[TRUTH:{tag}] is-generic={'parameter and default values' in seg and 'synthesize' not in seg}")
            print(f"[TRUTH:{tag}] has-grounded-call={'synthesize_grounded_answer' in seg or 'synthesize_grounded' in seg}")
    except SyntaxError as e:
        print(f"[TRUTH:{tag}] FILE HAS SYNTAX ERROR: {e}; this is the corrupted case")
    # import + self-test through REAL seam if module-level and importable
    sys.path.insert(0,str(ROOT))
    try:
        if tag=="agent":
            from benchmark.llm import _answer_from_observation as f
            r=f("The default value for mode is 'markdown', which renders the document server-side as Markdown.",
                "What is the default value for mode when rendering a Markdown document?")
            print(f"[TRUTH:{tag}] return-> {r!r}")
            print(f"[TRUTH:{tag}] grounded={'markdown' in r.lower() and 'default' in r.lower() and 'server' in r.lower()}")
        else:
            from workflow.deterministic_workflow import _step4_generate_answer as f
            r=f("What is the default value for mode when rendering a Markdown document?",
                [{"text":"The default value for mode is 'markdown', which renders the document server-side as Markdown."}],
                True, None, None)
            print(f"[TRUTH:{tag}] return-> {r!r}")
            print(f"[TRUTH:{tag}] grounded={'markdown' in r.lower() and 'default' in r.lower()}")
    except Exception as e:
        print(f"[TRUTH:{tag}] import/probe FAIL {type(e).__name__}: {str(e)[:100]}")