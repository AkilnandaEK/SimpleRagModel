"""Diagnostic: retrieval quality per scenario — does the evidence containing the golden answer
get surfaced by reference_search?"""
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.reference_search import ReferenceSearchInput, reference_search
from app.services.vector_store import _get_client

COLLECTION = "sdk-v3-strategy-b"

# Golden entries we care about (default 10 + the extras that failed)
key_tokens = {
    "easy:01": "markdown",
    "easy:04": "400",
    "medium:02": "generate-markdown",
    "medium:03": "swagger-codegen-ignore",
    "medium:05": "asyncio",
    "hard:01": "octocat",
    "hard:02": "negation",
    "hard:03": "additionalProperties",
    "hard:04": "maintainer_can_modify",
    "hard:07": "webclient",
    "hard:09": "wrap_tables",
    "easy:02": "io.swagger",
}
questions = {}
for fn in ("gs_easy.json", "gs_medium.json", "gs_hard.json"):
    with open(PROJECT_ROOT / "goldensets" / fn) as f:
        for e in json.load(f):
            questions[f"{e['level'].lower()}:{e['id']}"] = e["question"]

def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def find_in_corpus(token: str):
    """Return ids where the token appears in the chunk text."""
    client = _get_client()
    col = client.get_collection(name=COLLECTION)
    data = col.get(include=["documents"])
    hits = []
    for cid, doc in zip(data["ids"], data["documents"]):
        if doc and norm(token) in norm(doc):
            hits.append(cid)
    return hits


print(f"=== Does the answer-information even EXIST in the corpus? ===")
for key, token in key_tokens.items():
    hits = find_in_corpus(token)
    print(f"  {key:10s} token '{token:25s}' in corpus chunks: {len(hits)} -> {hits[:5]}")

print()
print("=== Does reference_search top-5 surface the evidence? ===")
for key, token in key_tokens.items():
    q = questions.get(key, "?")
    res = reference_search(ReferenceSearchInput(query=q, top_k=5), collection_name=COLLECTION)
    surfaced = [r.chunk_id for r in res.results if r.text and norm(token) in norm(r.text)]
    top_ids = ", ".join(r.chunk_id for r in res.results[:5])
    print(f"  {key:10s} top-5 -> [{top_ids}]  | token surfaced in top5: {len(surfaced)}")