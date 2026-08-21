"""
scripts/eval_mrr.py
-------------------
Offline MRR@k evaluation for the hybrid retriever.

Usage (from the repo root, with the venv active):

    python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json
    python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json --top-k 3
    python scripts/eval_mrr.py --golden-set eval/golden_set.sdk-v3.json --json report.json

The collection comes from the golden set's 'collection_name'; --collection
overrides it. Runs the real retrieval stack (embedder + BM25 + RRF), so no
server needs to be running, but the collection must already be indexed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/eval_mrr.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.mrr import MrrReport, evaluate_mrr, load_golden_set  # noqa: E402


def _print_report(report: MrrReport) -> None:
    misses = [item for item in report.evaluations if item.first_relevant_rank is None]

    print()
    print(f"  Collection : {report.collection_name}")
    print(f"  Queries    : {report.query_count}")
    print(f"  Cutoff     : top_k={report.top_k}")
    print(f"  Split      : {report.split or 'all'}")
    print()
    print(f"  {'QID':<6} {'Split':<6} {'RR':>7}  {'Rank':>5}  Question")
    print(f"  {'-' * 6} {'-' * 6} {'-' * 7}  {'-' * 5}  {'-' * 45}")

    for item in report.evaluations:
        rank = "-" if item.first_relevant_rank is None else str(item.first_relevant_rank)
        question = item.question if len(item.question) <= 45 else item.question[:42] + "..."
        print(
            f"  {item.id:<6} {item.split:<6} {item.reciprocal_rank:>7.4f}  {rank:>5}  {question}"
        )

    print()
    for score in report.split_scores:
        print(f"  MRR@{report.top_k} [{score.split:<4}] = {score.mrr:.4f}  (n={score.query_count})")
    print(f"  MRR@{report.top_k} [all ] = {report.mrr:.4f}  (n={report.query_count})")

    if misses:
        print()
        print(f"  {len(misses)} query(s) retrieved nothing relevant in the top {report.top_k}:")
        for item in misses:
            print(f"    {item.id}: expected {item.expected_chunk_ids}")
            print(f"        got      {item.retrieved_chunk_ids}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute MRR@k for the hybrid retriever.")
    parser.add_argument(
        "--golden-set",
        required=True,
        help="Path to the golden-set JSON file.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Collection to evaluate (overrides the golden set's collection_name).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=0,
        help="Retrieval cutoff k. 0 (default) uses settings.top_k.",
    )
    parser.add_argument(
        "--split",
        default=None,
        choices=["dev", "test"],
        help="Restrict to one split. Omit to score everything (still broken down per split).",
    )
    parser.add_argument(
        "--json",
        dest="json_out",
        default=None,
        help="Also write the full report to this path as JSON.",
    )
    args = parser.parse_args()

    try:
        golden_set, default_collection = load_golden_set(args.golden_set)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    collection_name = args.collection or default_collection
    if not collection_name:
        print(
            "error: no collection specified. Add 'collection_name' to the golden set "
            "or pass --collection.",
            file=sys.stderr,
        )
        return 2

    try:
        report = evaluate_mrr(collection_name, golden_set, top_k=args.top_k, split=args.split)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_report(report)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"  Report written to {out_path}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
