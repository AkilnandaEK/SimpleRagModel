"""Diagnostic: run agent + workflow on selected positive scenarios and dump evaluation details."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.config import load_config_from_env
from eval.benchmark_runner import run_benchmark

config = load_config_from_env()
print("mode:", config.llm.mode, "| collection:", config.retrieval.collection_name)

scenarios = ["easy:01", "easy:04", "medium:02", "medium:05", "hard:01", "hard:04",
             "medium:03", "hard:07", "easy:02", "hard:02"]
out = run_benchmark(config, scenario_ids=scenarios, verbose=False)

print(f"\n{'='*90}")
print(f"AGENT success: {out.agent_metrics.successful_count}/{out.agent_metrics.total_count} "
      f"({out.agent_metrics.success_rate:.0f}%)")
print(f"WORKFLOW success: {out.workflow_metrics.successful_count}/{out.workflow_metrics.total_count} "
      f"({out.workflow_metrics.success_rate:.0f}%)")
print(f"{'='*90}")

for r in out.scenario_results:
    e = r.entry
    print(f"\n[Scenario {e.id} | {e.level}] {'NEG' if e.is_negative_case else 'POS'}")
    print(f"  Q: {e.question}")
    print(f"  Golden: {e.answer[:130]}")
    if r.agent_eval:
        print(f"  AGENT      correct={r.agent_eval.is_correct} match={r.agent_eval.match_type}")
        print(f"    answer: {r.agent_telemetry.answer[:180]}")
        print(f"    detail: {r.agent_eval.details[:160]}")
    if r.workflow_eval:
        print(f"  WORKFLOW   correct={r.workflow_eval.is_correct} match={r.workflow_eval.match_type}")
        print(f"    answer: {r.workflow_telemetry.answer[:180]}")
        print(f"    detail: {r.workflow_eval.details[:160]}")