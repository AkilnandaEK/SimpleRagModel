"""
Week 7 — Agent Loop vs Deterministic Workflow
Main entry point for running the benchmark.

Usage:
    python eval/run_benchmark.py                 # run 10-scenario race benchmark
    python eval/run_benchmark.py --full          # run all 45 golden-set scenarios
    python eval/run_benchmark.py --ids 01,02,03  # run specific scenario IDs
    python eval/run_benchmark.py --report FILE   # write report to FILE
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.config import load_config_from_env
from eval.benchmark_runner import run_benchmark
from eval.verdict import generate_verdict
from eval.golden_loader import load_all_golden_sets


def main() -> int:
    parser = argparse.ArgumentParser(description="Week 7 — Agent Loop vs Deterministic Workflow benchmark")
    parser.add_argument("--full", action="store_true", help="Run all golden-set scenarios (45)")
    parser.add_argument("--ids", type=str, default=None, help="Comma-separated scenario IDs to run")
    parser.add_argument("--report", type=str, default=None, help="Write report to this file")
    parser.add_argument("--verbose", action="store_true", default=True, help="Print per-scenario details")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-scenario output")
    args = parser.parse_args()

    config = load_config_from_env()

    if args.ids:
        scenario_ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    elif args.full:
        all_sets = load_all_golden_sets(config.golden_set_dir)
        scenario_ids = []
        for filename, gs in all_sets.items():
            level_prefix = filename.replace("gs_", "").replace(".json", "")
            for entry in gs.entries:
                scenario_ids.append(f"{level_prefix}:{entry.id}")
    else:
        scenario_ids = config.benchmark_scenario_ids

    print(f"Week 7 Benchmark — {len(scenario_ids)} scenarios")
    print(f"Scenario IDs: {', '.join(scenario_ids)}")

    output = run_benchmark(config, scenario_ids=scenario_ids, verbose=not args.quiet)
    report = generate_verdict(output, mode=config.llm.mode)

    print(report)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport written to: {args.report}")

        json_path = str(Path(args.report).with_suffix(".json"))
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"scenario_ids": output.scenario_ids,
                       "agent": output.agent_metrics.__dict__,
                       "workflow": output.workflow_metrics.__dict__,
                       "scenario_results": [
                           {"id": r.entry.id, "level": r.entry.level,
                            "agent_correct": r.agent_eval.is_correct if r.agent_eval else False,
                            "workflow_correct": r.workflow_eval.is_correct if r.workflow_eval else False}
                           for r in output.scenario_results
                       ]}, f, indent=2)
        print(f"JSON data written to: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())