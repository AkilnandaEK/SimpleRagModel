import sys
sys.path.insert(0, r"E:\week3")
import eval.offline_grounding as m
print("IMPORT-OK")
print("MODULE-FILE=", m.__file__)
q = "What is the default value for mode when rendering a Markdown document?"
ev = [{"text": "The default value for mode is 'markdown', which renders the document server-side."}]
ans = m.synthesize_grounded_answer(q, ev)
print("ANSWER=", repr(ans))
print("CONTAINS-markdown=", "markdown" in ans.lower())
print("CONTAINS-default=", "default" in ans.lower())
print("REFUSAL-EMPTY=", repr(m.synthesize_grounded_answer("Some unrelated question", [])))
