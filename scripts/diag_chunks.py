"""Diagnostic: print the actual chunk text for evidence-bearing chunks across scenarios."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.vector_store import _get_client

client = _get_client()
col = client.get_collection(name="sdk-v3-strategy-b")
data = col.get(include=["documents"])
by_id = dict(zip(data["ids"], data["documents"]))

wanted = {
    "easy:01 (markdown default)": ["github_combined_reference.pdf__chunk_6", "github_combined_reference.pdf__chunk_1", "github_combined_reference.pdf__chunk_3"],
    "easy:04 (400KB)": ["github_combined_reference.pdf__chunk_5"],
    "medium:02 (generate-markdown)": ["swagger_v3_reference.pdf__chunk_1"],
    "medium:03 (ignore wildcard)": ["swagger_v2_reference.pdf__chunk_4"],
    "medium:05 (asyncio)": ["swagger_v3_reference.pdf__chunk_6"],
    "hard:01 (context string->object)": ["github_combined_reference.pdf__chunk_7", "github_combined_reference.pdf__chunk_3"],
    "hard:02 (negation)": ["swagger_v3_reference.pdf__chunk_7"],
    "hard:03 (additionalProperties)": ["swagger_v3_reference.pdf__chunk_9", "swagger_v3_reference.pdf__chunk_8"],
    "hard:04 (maintainer_can_modify)": ["github_combined_reference.pdf__chunk_18"],
    "hard:07 (webclient)": ["swagger_v3_reference.pdf__chunk_4", "swagger_v3_reference.pdf__chunk_5"],
    "hard:09 (wrap_tables)": ["github_combined_reference.pdf__chunk_6"],
}

for label, ids in wanted.items():
    print(f"\n================ {label} ================")
    for cid in ids:
        doc = by_id.get(cid, "")
        if not doc:
            print(f"  [{cid}] MISSING")
            continue
        print(f"  ---- [{cid}] ----")
        print((doc[:600]).replace("\n", " | "))
        if len(doc) > 600:
            print("   ...(truncated)")