"""
eval/run_eval.py
----------------
Week 6 · Work Items 2 & 3 — One-command evaluation runner.

Runs the 28-case eval set (eval/eval_cases.json) against the existing
Week-5 docs assistant, prints a pass-rate table by taxonomy mode, and
runs the Work Item 3 deterministic assertions against each answer.

The preliminary pass/fail uses only deterministic ties into the existing
Week-5 application:

  * the assistant's own refusal classification (response_status:
    "answered" or "refused", from the prescribed fallback phrase in
    app/routes/query.py), and
  * which outcome the eval case's expected_behavior demands.

Work Item 3 adds four deterministic assertion criteria (see eval/assertions.py):
code_sample_parses, endpoint_exists, api_version_stated, and
deprecated_symbol_migration. These are reported in their own section,
separate from the (not-yet-implemented) LLM judge criteria, so the judge
prompt can exclude them when it is added.

Usage (from the repo root, with the venv active):

    python eval/run_eval.py
    python eval/run_eval.py --cases eval/eval_cases.json --out eval/results.json
    python eval/run_eval.py --assertions-only --out eval/results.json

Notes
-----
* Cases that reference the recipe corpus are routed to the recipe
  collection; all other cases are routed to the SDK v3 collection.
* A single failed/erroring case never aborts the run — it is recorded
  as status "error" and execution continues.
* The .env configuration is used as-is (same provider/model as Week 5);
  no model or retrieval setting is silently changed.
* --assertions-only recomputes assertions from a saved results file without
  re-running the assistant, for iteration on the assertion logic alone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from collections import Counter, OrderedDict

# Allow running from the repo root as ``python eval/run_eval.py``.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routes.query import query_document, QueryRequest  # noqa: E402

from eval.assertions import run_assertions, ASSERTION_CRITERIA  # noqa: E402

# Collection routing. The eval set spans two corpora: the SDK v3 docs and the
# recipe corpus. Which collection each case targets is derived here (it is not
# stored in eval_cases.json, and we do not change the dataset).
SDK_COLLECTION = "sdk-v3-strategy-a"
RECIPE_COLLECTION = "recipe_rag_test_corpus"

# Case IDs whose questions belong to the recipe corpus. Every other case is
# routed to the SDK v3 collection.
RECIPE_CASE_IDS = {
    "eval_013", "eval_014", "eval_015", "eval_016",
    "eval_017", "eval_020", "eval_027", "eval_028",
}


def _collection_for(case: dict) -> str:
    return RECIPE_COLLECTION if case["id"] in RECIPE_CASE_IDS else SDK_COLLECTION


def _expects_answer(case: dict) -> bool:
    """Deterministic expectation derived from the case's expected_behavior.

    If the expected behavior requires a refusal, the assistant must refuse;
    otherwise it must answer. Detected from the word "refuse" in the field
    written in Work Item 1 (e.g. eval_013-017, eval_019 expect a refusal;
    eval_020 and the factual/conceptual/version cases expect an answer).
    """
    behavior = (case.get("expected_behavior") or "").lower()
    return "refuse" not in behavior


async def _run_case(case: dict) -> dict:
    """Run a single case through the real Week-5 pipeline and score it.

    Returns a flat result dict. Never raises: any assistant error is captured
    and recorded as status "error" so the remaining cases still run.
    """
    case_id = case["id"]
    question = case["question"]
    taxonomy_mode = case["taxonomy_mode"]
    collection = _collection_for(case)
    expects_answer = _expects_answer(case)

    result = {
        "id": case_id,
        "taxonomy_mode": taxonomy_mode,
        "question": question,
        "collection_name": collection,
        "answer": None,
        "status": "error",
        "error": None,
    }

    try:
        response = await query_document(
            QueryRequest(
                question=question,
                collection_name=collection,
                debug=True,
            )
        )
    except Exception as exc:  # noqa: BLE001 — capture any assistant failure
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    answer = response.answer if response.answer is not None else ""
    result["answer"] = answer

    # Use the assistant's own refusal classification when available (debug
    # mode returns EvaluationDetails.response_status); fall back to checking
    # the prescribed refusal phrase directly.
    if response.evaluation is not None:
        response_status = response.evaluation.response_status
    else:
        refusal_trigger = "I don't have enough information in the provided document"
        response_status = "refused" if refusal_trigger.lower() in answer.lower() else "answered"
    result["refused"] = response_status == "refused"

    # Preliminary deterministic pass/fail (Work Item 3 adds assertions later).
    if not answer:
        result["status"] = "error"
        result["error"] = "assistant returned an empty answer"
        return result

    if expects_answer:
        passed = response_status == "answered"
    else:
        passed = response_status == "refused"

    result["status"] = "pass" if passed else "fail"
    if not passed:
        result["error"] = (
            f"expected {'answer' if expects_answer else 'refusal'} "
            f"but assistant {response_status}"
        )

    # Work Item 3 — deterministic assertions. Each criterion is checked against
    # the produced answer; non-applicable criteria are reported (not judged).
    result["assertions"] = run_assertions(case, answer)
    return result


def _save(path: Path, results: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)


def _print_assertion_summary(results: list) -> None:
    """Print the Work Item 3 assertion report.

    Deterministic assertion criteria are reported separately from the LLM judge
    criteria so the 4 deterministic checks can be excluded from the judge prompt
    when that is added. The judge is not implemented yet, hence "0".
    """
    print("\nWork Item 3 — evaluation criteria split")
    print("=" * 62)
    print()
    print("Deterministic assertion criteria: %d" % len(ASSERTION_CRITERIA))
    print("LLM-judged criteria:              0 (not implemented yet)")
    print()

    # Aggregate per criterion across all cases.
    totals: OrderedDict[str, dict] = OrderedDict(
        (c, {"applicable": 0, "passed": 0, "failed": 0, "not_applicable": 0})
        for c in ASSERTION_CRITERIA
    )
    for result in results:
        assertions = result.get("assertions") or {}
        for criterion in ASSERTION_CRITERIA:
            check = assertions.get(criterion)
            if not check:
                continue
            slot = totals[criterion]
            if not check.get("applicable"):
                slot["not_applicable"] += 1
            elif check.get("passed"):
                slot["passed"] += 1
            else:
                slot["failed"] += 1
            slot["applicable"] += int(bool(check.get("applicable")))

    header = f"{'Criterion':<28}{'Applicable':>11}{'Passed':>9}{'Failed':>9}{'N/A':>6}"
    print("Deterministic assertions")
    print("-" * 62)
    print(header)
    print("-" * 62)
    for criterion, stats in totals.items():
        print(
            f"{criterion:<28}{stats['applicable']:>11}{stats['passed']:>9}"
            f"{stats['failed']:>9}{stats['not_applicable']:>6}"
        )
    print("-" * 62)
    print()

    # Per-case failed assertions for visibility.
    print("Failed / non-applicable assertions by case:")
    for result in results:
        assertions = result.get("assertions") or {}
        lines = []
        for criterion in ASSERTION_CRITERIA:
            check = assertions.get(criterion)
            if not check:
                continue
            if check.get("applicable") and not check.get("passed"):
                lines.append(f"{criterion}: {check['details']}")
        if lines:
            print(f"  {result['id']}")
            for line in lines:
                print(f"    - {line}")
    print()


def _print_table(per_mode: OrderedDict, total: dict) -> None:
    line = "-" * 62
    header = f"{'Mode':<26}{'Cases':>7}{'Passed':>9}{'Failed':>9}{'Pass Rate':>11}"
    print("\nWEEK 6 EVAL RESULTS")
    print("=" * 62)
    print()
    print(header)
    print(line)
    for mode, stats in per_mode.items():
        rate = (stats["passed"] / stats["cases"] * 100) if stats["cases"] else 0.0
        print(
            f"{mode:<26}{stats['cases']:>7}{stats['passed']:>9}"
            f"{stats['failed']:>9}{rate:>10.1f}%"
        )
    print(line)
    total_rate = (total["passed"] / total["cases"] * 100) if total["cases"] else 0.0
    print(
        f"{'TOTAL':<26}{total['cases']:>7}{total['passed']:>9}"
        f"{total['failed']:>9}{total_rate:>10.1f}%"
    )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Week-6 eval set against the docs assistant.")
    parser.add_argument(
        "--cases",
        default=str(ROOT / "eval" / "eval_cases.json"),
        help="Path to the eval cases JSON (default: eval/eval_cases.json).",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "eval" / "results.json"),
        help="Path to write per-case results (default: eval/results.json).",
    )
    parser.add_argument(
        "--assertions-only",
        action="store_true",
        help="Do not re-run the assistant: recompute deterministic assertions "
        "from an existing result/cases file pair and print the assertion summary.",
    )
    args = parser.parse_args()

    cases_path = Path(args.cases)
    out_path = Path(args.out)

    if not cases_path.exists():
        print(f"error: eval cases file not found: {cases_path}", file=sys.stderr)
        return 2

    try:
        with open(cases_path, "r", encoding="utf-8") as fh:
            cases = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {cases_path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(cases, list) or not cases:
        print(f"error: {cases_path} does not contain a non-empty list of cases", file=sys.stderr)
        return 2

    case_by_id = {case["id"]: case for case in cases}

    if args.assertions_only:
        if not out_path.exists():
            print(f"error: results file not found: {out_path}", file=sys.stderr)
            return 2
        with open(out_path, "r", encoding="utf-8") as fh:
            results = json.load(fh)
        # Recompute assertions from the stored answers (no assistant re-run).
        for result in results:
            case = case_by_id.get(result.get("id"), {})
            result["assertions"] = run_assertions(case, result.get("answer") or "")
        _save(out_path, results)
        _print_assertion_summary(results)
        return 0

    results = asyncio.run(_run_all(cases))

    # Save machine-readable results first (before printing, so a later UI has
    # the full data regardless of terminal output).
    _save(out_path, results)
    print(f"Results written to {out_path}")

    _print_assertion_summary(results)

    # Per-mode aggregation, preserving first-seen mode order.
    per_mode: OrderedDict[str, dict] = OrderedDict()
    for result in results:
        mode = result["taxonomy_mode"]
        if mode not in per_mode:
            per_mode[mode] = {"cases": 0, "passed": 0, "failed": 0}
        per_mode[mode]["cases"] += 1
        if result["status"] == "pass":
            per_mode[mode]["passed"] += 1
        else:
            per_mode[mode]["failed"] += 1

    total = {"cases": len(results), "passed": 0, "failed": 0}
    for result in results:
        if result["status"] == "pass":
            total["passed"] += 1
        else:
            total["failed"] += 1

    _print_table(per_mode, total)

    # Brief per-case status line so failures are visible in the terminal.
    print("Per-case status:")
    for result in results:
        marker = "PASS" if result["status"] == "pass" else (
            "ERROR" if result["status"] == "error" else "FAIL"
        )
        print(f"  {result['id']} {marker:<6} {result['question']}")
    print()

    return 0


async def _run_all(cases: list) -> list:
    results = []
    for case in cases:
        results.append(await _run_case(case))
    return results


if __name__ == "__main__":
    raise SystemExit(main())
