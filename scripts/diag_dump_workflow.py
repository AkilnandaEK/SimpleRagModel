"""Dump exact bytes of the workflow offline answer branch + imports."""
from pathlib import Path

p = Path(r"E:\week3\workflow\deterministic_workflow.py")
lines = p.read_text(encoding="utf-8").splitlines()

print("=== IMPORT BLOCK (first 22 lines escaped) ===")
for i, ln in enumerate(lines[:24], 1):
    print(f"{i:>3}: {ln.encode('unicode_escape').decode('ascii')}")

print()
print("=== _step4_generate_answer region (escaped) ===")
start, end = None, None
for i, ln in enumerate(lines, 1):
    if "def _step4_generate_answer" in ln:
        start = i - 1
    if start and i >= start and i <= start + 40:
        end = i
        print(f"{i:>3}: {ln.encode('unicode_escape').decode('ascii')}")
    if end and i > start + 40:
        break
