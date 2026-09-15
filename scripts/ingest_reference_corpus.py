"""
scripts/ingest_reference_corpus.py
--------------------------------------------------
Utility: ingest the Week 7 reference corpus PDFs into the retrieval collection.

The golden sets reference these documents:
    github_combined_reference.pdf
    swagger_v2_reference.pdf
    swagger_v3_reference.pdf

They are not bundled with the repository. When supplied, run:
    python scripts/ingest_reference_corpus.py --dir <folder> --collection <name>

The benchmark will then be able to answer positive cases with real evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.chunker import pdf_to_chunks
from app.services.embedder import embed_texts
from app.services.vector_store import add_chunks, list_collections


REFERENCE_FILES = {
    "github_combined_reference.pdf",
    "swagger_v2_reference.pdf",
    "swagger_v3_reference.pdf",
}


def ingest_pdf(file_path: Path, collection_name: str) -> int:
    """Chunk a PDF and add it to the target collection. Returns chunk count."""
    content_bytes = file_path.read_bytes()
    chunks = pdf_to_chunks(content_bytes)

    chunk_texts = [str(c) for c in chunks]
    embeddings = embed_texts(chunk_texts)

    metadatas = []
    for i, chunk in enumerate(chunks):
        meta = dict(getattr(chunk, "metadata", None) or {})
        meta.setdefault("source_file", file_path.name)
        meta.setdefault("page_id", str(meta.get("page_id") or file_path.stem))
        meta.setdefault("sdk_version", "v3")
        meta.setdefault("page_type", "reference")
        metadatas.append(meta)

    stored = add_chunks(
        collection_name=collection_name,
        chunks=chunk_texts,
        embeddings=embeddings,
        source_filename=file_path.name,
        metadatas=metadatas,
    )
    return stored


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Week 7 reference corpus PDFs into the retrieval collection.")
    parser.add_argument("--dir", type=str, default=".", help="Folder containing the reference PDFs.")
    parser.add_argument("--collection", type=str, default="sdk-v3-strategy-b", help="Target collection name.")
    args = parser.parse_args()

    source_dir = Path(args.dir)
    if not source_dir.is_dir():
        print(f"ERROR: '{args.dir}' is not a directory.")
        return 1

    found = []
    for candidate in REFERENCE_FILES:
        p = source_dir / candidate
        if p.is_file():
            found.append(p)

    if not found:
        print("No reference corpus PDFs found. Expected in this folder:")
        for fn in sorted(REFERENCE_FILES):
            print(f"  - {fn}")
        print("\nExisting collections:")
        for col in list_collections():
            print(f"  - {col['name']} ({col['count']} chunks)")
        return 2

    print(f"Collections: {args.collection}")
    total = 0
    for pdf in found:
        n = ingest_pdf(pdf, args.collection)
        total += n
        print(f"  Ingested {pdf.name}: {n} chunks")

    from app.services.hybrid_retrieval import refresh_bm25_index
    refresh_bm25_index(args.collection)

    print(f"\nTotal chunks stored: {total}")
    print("Reference corpus ready. Run: python eval/run_benchmark.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())