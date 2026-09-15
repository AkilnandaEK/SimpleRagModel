"""
eval/run_judge.py
-----------------
Week 6 · Work Items 6 & 9 — LLM-as-judge execution and agreement calculation.

Two strictly separated phases so that human labels never influence judge
decisions:

  run_judge(<version>)
      Loads ONLY the prompt (eval/judge_<version>.txt) and the assistant
      answers (eval/results.json) for the 25 selected cases. It does NOT
      read eval/labels_25.json. Each answer is sent to the active project
      LLM provider (unchanged model/config) and the judge's binary label is
      parsed and validated. Output is written to
      eval/judge_<version>_results.json.

  calculate_agreement(<version>)
      Loads eval/judge_<version>_results.json and eval/labels_25.json and
      computes exact binary agreement. For v1 the output is written to
      eval/agreement_before.json (the locked baseline). For v2 it is written
      to eval/agreement_after.json and compared against the locked v1
      baseline stored in eval/agreement_before.json.

Usage (from repo root, with venv active):

    python eval/run_judge.py run --version v1
    python eval/run_judge.py agree --version v1
    python eval/run_judge.py run --version v2
    python eval/run_judge.py agree --version v2

The judge NEVER loads the human labels, and the agreement phase never calls
the model, so no human-label leakage into judge decisions is possible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.llm_provider import generate_answer  # noqa: E402

EVAL = Path(__file__).resolve().parent

MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Phase 1: run the judge (human labels are NOT loaded here)
# ---------------------------------------------------------------------------

def _load_judge_inputs() -> list[dict]:
    """Build judge inputs for the 25 selected cases from results.json only.

    The 25 case IDs come from eval/blind_labels_25.json (the pre-labeling
    selection sheet, whose human_label fields are all null). eval/labels_25.json
    -- which carries the human 0/1 judgments -- is intentionally NEVER read in
    this phase, so no human label can influence a judge decision.
    """
    selection_path = EVAL / "blind_labels_25.json"
    results_path = EVAL / "results.json"

    with open(selection_path, "r", encoding="utf-8") as fh:
        selected_cases = json.load(fh)
    labeled_ids = [c["id"] for c in selected_cases]

    with open(results_path, "r", encoding="utf-8") as fh:
        results = json.load(fh)
    result_by_id = {c["id"]: c for c in results}

    inputs = []
    for cid in labeled_ids:
        res = result_by_id.get(cid)
        if res is None:
            raise ValueError(f"case {cid} not found in results.json")
        inputs.append(
            {
                "id": cid,
                "taxonomy_mode": res.get("taxonomy_mode"),
                "question": res.get("question"),
                "answer": res.get("answer"),
            }
        )
    return inputs


def _build_prompt(case: dict, prompt_template: str) -> str:
    return (
        prompt_template
        + "\n\n"
        + "USER QUESTION:\n"
        + str(case["question"])
        + "\n\n"
        + "ASSISTANT ANSWER:\n"
        + str(case["answer"])
    )


def _parse_label(raw: str) -> int:
    """Deterministically parse the judge's binary label.

    Accept only explicit integer 0 or 1. Raises ValueError on anything else.
    """
    text = (raw or "").strip()
    # Try to extract a JSON object and read its "label" key.
    import re

    match = re.search(r"\{[^{}]*\}", text)
    if match:
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and "label" in obj:
            val = obj["label"]
            if isinstance(val, bool):
                raise ValueError(f"label must be int 0/1, got bool {val!r}")
            return int(val)

    # Fallback: look for an isolated "label": <int> pattern.
    m2 = re.search(r'"label"\s*:\s*(0|1)\b', text)
    if m2:
        return int(m2.group(1))

    raise ValueError(f"unparseable judge label from raw output: {raw!r}")


def _call_judge(prompt: str) -> str:
    """Call the active project LLM with a small retry policy."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return generate_answer(prompt).raw_text
        except Exception as exc:  # noqa: BLE001 — transient provider errors
            last_err = exc
            if attempt == MAX_RETRIES:
                raise
    raise RuntimeError(f"judge call failed after {MAX_RETRIES} attempts: {last_err}")


def run_judge(version: str) -> list[dict]:
    judge_path = EVAL / f"judge_{version}.txt"
    with open(judge_path, "r", encoding="utf-8") as fh:
        prompt_template = fh.read()

    inputs = _load_judge_inputs()
    outputs = []
    for idx, case in enumerate(inputs, start=1):
        record = {
            "id": case["id"],
            "judge_version": version,
            "question": case["question"],
            "answer": case["answer"],
            "label": None,
            "reason": None,
            "raw": None,
            "error": None,
        }
        prompt = _build_prompt(case, prompt_template)
        try:
            raw = _call_judge(prompt)
            record["raw"] = raw
            label = _parse_label(raw)
            if label not in (0, 1):
                raise ValueError(f"label {label!r} not binary")
            record["label"] = label
            # Best-effort reason extraction (kept separate, optional).
            import re
            m = re.search(r'"reason"\s*:\s*"([^"]*)"', raw)
            if m:
                record["reason"] = m.group(1)
        except Exception as exc:  # noqa: BLE001 — record, don't fabricate
            record["error"] = f"{type(exc).__name__}: {exc}"
        outputs.append(record)
        print(f"[{idx}/{len(inputs)}] {case['id']}: label={record['label']} "
              f"error={'yes' if record['error'] else 'no'}")

    out_path = EVAL / f"judge_{version}_results.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(outputs, fh, indent=2, ensure_ascii=False)
    print(f"Judge {version.upper()} results written to {out_path}")
    return outputs


# ---------------------------------------------------------------------------
# Phase 2: agreement (model is NOT called here)
# ---------------------------------------------------------------------------

def _load_judge_results(version: str) -> list[dict]:
    path = EVAL / f"judge_{version}_results.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_human_labels() -> dict:
    path = EVAL / "labels_25.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def calculate_agreement(version: str) -> dict:
    judge = _load_judge_results(version)
    humans = _load_human_labels()

    human_by_id = {c["id"]: c for c in humans}
    matched = 0
    disagreements: list[dict] = []
    valid_judge_labels = 0

    for rec in judge:
        cid = rec["id"]
        if rec.get("error"):
            continue
        judge_label = rec.get("label")
        if judge_label is None:
            continue
        valid_judge_labels += 1
        human = human_by_id.get(cid)
        human_label = human.get("human_label") if human else None
        if human_label == judge_label:
            matched += 1
        else:
            disagreements.append(
                {
                    "id": cid,
                    "taxonomy_mode": rec.get("taxonomy_mode")
                    or (human.get("taxonomy_mode") if human else None),
                    "question": rec.get("question"),
                    "human_label": human_label,
                    "judge_label": judge_label,
                }
            )

    agreement_percent = (
        round(matched / valid_judge_labels * 100, 2) if valid_judge_labels else 0.0
    )

    summary = {
        "judge_version": version,
        "cases_compared": valid_judge_labels,
        "valid_judge_labels": valid_judge_labels,
        "matches": matched,
        "disagreements": len(disagreements),
        "agreement_percent": agreement_percent,
    }

    # Before/after naming: v1 -> agreement_before, v2 -> agreement_after.
    if version == "v1":
        out_path = EVAL / "agreement_before.json"
        disc_path = EVAL / "judge_v1_disagreements.txt"
    else:
        out_path = EVAL / "agreement_after.json"
        disc_path = EVAL / "judge_v2_disagreements.txt"

        # Compare against the locked V1 baseline.
        baseline_path = EVAL / "agreement_before.json"
        if baseline_path.exists():
            with open(baseline_path, "r", encoding="utf-8") as fh:
                baseline = json.load(fh)
            delta = agreement_percent - baseline["agreement_percent"]
            summary["agreement_before_percent"] = baseline["agreement_percent"]
            summary["agreement_delta_percent"] = round(delta, 2)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # Plain-text disagreement list for the report.
    with open(disc_path, "w", encoding="utf-8") as fh:
        fh.write(f"Judge {version.upper()} disagreements (human vs judge)\n")
        fh.write("=" * 60 + "\n")
        if not disagreements:
            fh.write("none\n")
        for d in disagreements:
            fh.write(f"{d['id']}\n")
            fh.write(f"  taxonomy_mode: {d['taxonomy_mode']}\n")
            fh.write(f"  question:      {d['question']}\n")
            fh.write(f"  human_label:   {d['human_label']}\n")
            fh.write(f"  judge_label:   {d['judge_label']}\n\n")
    print(f"Agreement written to {out_path}")
    print(f"Disagreements written to {disc_path}")
    print(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Week 6 LLM judge.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run a judge version and save results.")
    p_run.add_argument("--version", required=True, choices=["v1", "v2"])
    p_run.set_defaults(func=lambda a: run_judge(a.version))

    p_agree = sub.add_parser("agree", help="Compute agreement (before/after).")
    p_agree.add_argument("--version", required=True, choices=["v1", "v2"])
    p_agree.set_defaults(func=lambda a: calculate_agreement(a.version))

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
