"""Dump the exact boilerplate blocks in the two files using ASCII escapes.
Proof that the read of these regions is reliable."""
from pathlib import Path

ROOT = Path(r"E:\week3")

def dump_region(rel, lo, hi):
    p = ROOT / rel
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"##### {rel}  lines {lo}-{hi} (file={len(lines)} lines)")
    for i in range(lo - 1, min(hi, len(lines))):
        ln = lines[i]
        a = ln.encode("utf-8").decode("ascii", errors="backslashreplace")
        print(f"{i + 1:>4}| {a}")
    print()

dump_region(r"workflow\deterministic_workflow.py", 94, 124)
dump_region(r"benchmark\llm.py", 101, 130)
