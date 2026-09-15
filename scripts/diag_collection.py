"""Diagnostic: inspect collection contents vs golden expected chunk ids."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.vector_store import _get_client, list_collections

COLLECTION = "sdk-v3-strategy-b"

print("COLLECTIONS:")
for c in list_collections():
    print("  ", c)
print()

# Golden expected chunk ids
all_expected = set()
for fn in ("gs_easy.json", "gs_medium.json", "gs_hard.json"):
    with open(PROJECT_ROOT / "goldensets" / fn) as f:
        entries = json.load(f)
    for e in entries:
        eid = e.get("expected_chunk_id")
        if eid:
            for part in eid.split(";"):
                all_expected.add(part.strip())
print("Golden expected_chunk_id(s):")
for cid in sorted(all_expected):
    print("  ", cid)
print()

client = _get_client()
col = client.get_collection(name=COLLECTION)
data = col.get(include=["documents", "metadatas"])
ids = data["ids"]
docs = data["documents"]
metas = data["metadatas"]
print(f"{COLLECTION} chunk count: {len(ids)}")

by_id = dict(zip(ids, metas))
print("\nChunk ids in collection (with expected-id match marked):")
for cid in sorted(ids):
    marker = "  <-- EXPECTED" if cid in all_expected else ""
    meta = by_id.get(cid) or {}
    src = meta.get("source") or meta.get("source_file") or "?"
    print(f"  {cid}  | src={src}{marker}")

missing = sorted(all_expected - set(ids))
print("\nExpected ids MISSING from collection:")
if missing:
    for m in missing:
        print("  ", m)
else:
    print("   (none - all expected ids present)")