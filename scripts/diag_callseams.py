"""Find every call site of OfflineReasoner.decide / decide( and how last_observation
and evidence are threaded, across agent + workflow + benchmark, ASCII-safe."""
from pathlib import Path

ROOT = Path(r"E:\week3")

KEY = ["OfflineReasoner", "decide(", "last_observation", "evidence_count", "is_answerable", "REFUSAL_ANSWER", "_answer_from_observation", "chunks_retrieved"]
for rel in ["agent/agent_loop.py", "workflow/deterministic_workflow.py", "workflow/deterministic_workflow.py", "benchmark/llm.py"]:
    p = ROOT / rel
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    print("=" * 80)
    print(f"{rel:55s} | {len(lines)} lines")
    print("=" * 80)
    for i, ln in enumerate(lines, 1):
        low = ln.lower()
        hit = any(k.lower() in low for k in KEY)
        if not hit:
            continue
        ascii_ln = ln.encode("utf-8").decode("ascii", errors="backslashreplace")
        print(f"{i:>5}| {ascii_ln.strip()[:120]}")
    print()
