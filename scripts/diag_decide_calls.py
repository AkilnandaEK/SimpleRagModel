"""Find .decide( call sites in agent + workflow + any module. ASCII-safe."""
from pathlib import Path

ROOT = Path(r"E:\week3")
needles = ["OfflineReasoner", "reasoner.decide", ".decide(", "decide(",
           "last_observation", "state.evidence", "_step4_generate_answer",
           "_step3_analyze", "_step2_retrieve", "_step1_search"]

for rel in ["agent/agent_loop.py", "workflow/deterministic_workflow.py",
            "benchmark/llm.py", "app/services/generator/offline_loop.py"]:
    p = ROOT / rel
    if not p.exists():
        print(f"### MISSING: {rel}")
        continue
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    print("=" * 80)
    print(rel, f"({len(lines)} lines)")
    print("=" * 80)
    for i, ln in enumerate(lines, 1):
        is_hit = any(k in ln for k in needles)
        if not is_hit:
            continue
        a = ln.encode("utf-8").decode("ascii", errors="backslashreplace")
        print(f"{i:>5}| {a}")
    print()
