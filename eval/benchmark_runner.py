"""
eval/benchmark_runner.py
--------------------------------------
Runs both the agent and the deterministic workflow against golden-set
scenarios and produces comparable metrics.

Each scenario's execution telemetry is persisted into the shared Week 3 trace
store (``traces/traces.jsonl``) via ``app.services.tracing.save_trace``.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmark.config import BenchmarkConfig
from eval.evaluator import EvalResult, evaluate_answer
from eval.golden_loader import (
    GoldenEntry,
    GoldenSet,
    load_all_golden_sets,
    get_all_entries,
)
from agent.agent_loop import run_agent
from workflow.deterministic_workflow import run_workflow
from telemetry.telemetry import ExecutionTelemetry, BenchmarkReport

from app.services.tracing import save_trace


@dataclass
class ScenarioResult:
    entry: GoldenEntry
    agent_eval: EvalResult | None = None
    workflow_eval: EvalResult | None = None
    agent_telemetry: ExecutionTelemetry | None = None
    workflow_telemetry: ExecutionTelemetry | None = None


@dataclass
class BenchmarkMetrics:
    architecture: str
    success_rate: float = 0.0
    successful_count: int = 0
    total_count: int = 0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    avg_total_tokens: float = 0.0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_cost_per_run: float = 0.0
    cost_per_success: float = 0.0


@dataclass
class BenchmarkOutput:
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    agent_metrics: BenchmarkMetrics = field(default_factory=lambda: BenchmarkMetrics(architecture="agent"))
    workflow_metrics: BenchmarkMetrics = field(default_factory=lambda: BenchmarkMetrics(architecture="workflow"))
    scenario_ids: list[str] = field(default_factory=list)
    total_scenarios: int = 0


def _persist_telemetry(telemetry: ExecutionTelemetry) -> None:
    """Persist one execution record into the shared traces/traces.jsonl store.

    Never fails the benchmark — tracing is best-effort.
    """
    try:
        save_trace(telemetry.to_dict())
    except Exception:
        pass


def _compute_metrics(
    telemetries: list[ExecutionTelemetry],
    eval_results: list[EvalResult],
    architecture: str,
) -> BenchmarkMetrics:
    """Compute aggregated metrics from individual run telemetry."""
    if not telemetries:
        return BenchmarkMetrics(architecture=architecture)

    successful = sum(1 for e in eval_results if e.is_correct)
    total = len(telemetries)

    latencies = [t.latency_ms for t in telemetries]
    p50 = statistics.median(latencies) if latencies else 0.0
    p99 = sorted(latencies)[int(len(sorted(latencies)) * 0.99)] if len(latencies) >= 2 else (latencies[0] if latencies else 0.0)

    input_tokens = [t.input_tokens for t in telemetries]
    output_tokens = [t.output_tokens for t in telemetries]
    total_tokens_list = [t.input_tokens + t.output_tokens for t in telemetries]
    costs = [t.estimated_cost_usd for t in telemetries]

    avg_in = statistics.mean(input_tokens) if input_tokens else 0.0
    avg_out = statistics.mean(output_tokens) if output_tokens else 0.0
    avg_tot = statistics.mean(total_tokens_list) if total_tokens_list else 0.0
    total_tok = sum(total_tokens_list)
    total_cost = sum(costs)
    avg_cost = total_cost / max(total, 1)
    cost_per_success = total_cost / max(successful, 1)

    return BenchmarkMetrics(
        architecture=architecture,
        success_rate=successful / max(total, 1) * 100,
        successful_count=successful,
        total_count=total,
        p50_latency_ms=round(p50, 2),
        p99_latency_ms=round(p99, 2),
        avg_input_tokens=round(avg_in, 1),
        avg_output_tokens=round(avg_out, 1),
        avg_total_tokens=round(avg_tot, 1),
        total_tokens=total_tok,
        total_cost_usd=round(total_cost, 6),
        avg_cost_per_run=round(avg_cost, 6),
        cost_per_success=round(cost_per_success, 6),
    )


def _expand_scenario_keys(
    all_entries: list[GoldenEntry],
    scenario_keys: list[str],
) -> list[GoldenEntry]:
    """
    Map scenario selection keys onto golden entries.

    Supported key forms:
      "01"           -> every entry whose id == "01" across all levels
      "easy:01"      -> only the Easy entry with id "01"
      "easy/01", "Easy-01" also accepted (case-insensitive level keyword)
    """
    selected: list[GoldenEntry] = []
    for key in scenario_keys:
        key = key.strip()
        matched = False
        if ":" in key or "/" in key or "-" in key:
            parts = None
            for sep in (":", "/", "-"):
                if sep in key:
                    parts = [p.strip() for p in key.split(sep)]
                    break
            if parts and len(parts) == 2 and parts[1].isdigit():
                level_part = parts[0].lower()
                id_part = parts[1]
                level_map = {
                    "easy": "Easy", "medium": "Medium", "hard": "Hard",
                }
                level = level_map.get(level_part)
                if level:
                    for entry in all_entries:
                        if entry.level == level and entry.id == id_part:
                            selected.append(entry)
                            matched = True
                    continue
        # plain id fallback
        for entry in all_entries:
            if entry.id == key:
                selected.append(entry)
                matched = True
        if not matched:
            raise ValueError(f"Scenario key '{key}' matched no golden entries")
    return selected


def _warmup(config: BenchmarkConfig) -> None:
    """Warm up the embeddings + ChromaDB so latency measurements are fair."""
    try:
        from app.services.embedder import embed_query
        from app.services.hybrid_retrieval import hybrid_query_chunks
        embed_query("warmup")
        hybrid_query_chunks(
            collection_name=config.retrieval.collection_name,
            query="warmup",
            query_embedding=[0.0] * 384,
            top_k=1,
        )
    except Exception:
        pass


def run_benchmark(
    config: BenchmarkConfig,
    scenario_ids: list[str] | None = None,
    verbose: bool = True,
) -> BenchmarkOutput:
    """
    Run both agent and workflow on the specified scenarios.
    If scenario_ids is None, uses config.benchmark_scenario_ids.
    """
    if scenario_ids is None:
        scenario_ids = config.benchmark_scenario_ids

    _warmup(config)

    golden_dir = config.golden_set_dir
    all_sets = load_all_golden_sets(golden_dir)
    all_entries = get_all_entries(all_sets)

    entries_to_run = _expand_scenario_keys(all_entries, scenario_ids)

    entries_to_run.sort(key=lambda e: e.id)

    output = BenchmarkOutput(
        scenario_ids=[k for k in scenario_ids],
        total_scenarios=len(entries_to_run),
    )

    agent_telemetries = []
    agent_evals = []
    workflow_telemetries = []
    workflow_evals = []

    for i, entry in enumerate(entries_to_run):
        if verbose:
            print(f"\n{'='*60}")
            print(f"  Scenario {entry.id} [{entry.level}] ({'NEGATIVE' if entry.is_negative_case else 'POSITIVE'})")
            print(f"  Question: {entry.question[:80]}...")
            print(f"{'='*60}")

        # Run agent
        if verbose:
            print(f"\n  --- Agent Run ---")
        try:
            agent_state, agent_cb, agent_tel = run_agent(
                entry.question, config, config.retrieval.collection_name,
            )
            agent_tel.scenario_id = entry.id
            agent_tel.difficulty = entry.level
            agent_tel.is_negative_case = entry.is_negative_case
            agent_tel.expected_behavior = entry.expected_behavior or "answer_correctly"

            agent_eval = evaluate_answer(entry, agent_state.answer, agent_tel)
            agent_tel.success = agent_eval.is_correct

            agent_tel.answer = agent_state.answer
            _persist_telemetry(agent_tel)

            agent_telemetries.append(agent_tel)
            agent_evals.append(agent_eval)

            if verbose:
                print(f"    Answer: {agent_state.answer[:120]}...")
                print(f"    Correct: {agent_eval.is_correct} ({agent_eval.match_type})")
                print(f"    Latency: {agent_tel.latency_ms:.0f}ms | Tokens: {agent_tel.input_tokens + agent_tel.output_tokens}")
        except Exception as exc:
            if verbose:
                print(f"    Agent ERROR: {exc}")
            fallback_tel = ExecutionTelemetry(
                architecture="agent",
                scenario_id=entry.id,
                difficulty=entry.level,
                error=str(exc),
                answer="",
                is_negative_case=entry.is_negative_case,
            )
            fallback_eval = EvalResult(
                scenario_id=entry.id,
                level=entry.level,
                is_correct=False,
                match_type="incorrect",
                details=f"Agent crashed: {exc}",
                telemetry=fallback_tel,
            )
            _persist_telemetry(fallback_tel)
            agent_telemetries.append(fallback_tel)
            agent_evals.append(fallback_eval)

        # Run workflow
        if verbose:
            print(f"\n  --- Workflow Run ---")
        try:
            wf_state, wf_cb, wf_tel = run_workflow(
                entry.question, config, config.retrieval.collection_name,
            )
            wf_tel.scenario_id = entry.id
            wf_tel.difficulty = entry.level
            wf_tel.is_negative_case = entry.is_negative_case
            wf_tel.expected_behavior = entry.expected_behavior or "answer_correctly"

            wf_eval = evaluate_answer(entry, wf_state.answer, wf_tel)
            wf_tel.success = wf_eval.is_correct

            wf_tel.answer = wf_state.answer
            _persist_telemetry(wf_tel)

            workflow_telemetries.append(wf_tel)
            workflow_evals.append(wf_eval)

            if verbose:
                print(f"    Answer: {wf_state.answer[:120]}...")
                print(f"    Correct: {wf_eval.is_correct} ({wf_eval.match_type})")
                print(f"    Latency: {wf_tel.latency_ms:.0f}ms | Tokens: {wf_tel.input_tokens + wf_tel.output_tokens}")
        except Exception as exc:
            if verbose:
                print(f"    Workflow ERROR: {exc}")
            fallback_tel = ExecutionTelemetry(
                architecture="workflow",
                scenario_id=entry.id,
                difficulty=entry.level,
                error=str(exc),
                answer="",
                is_negative_case=entry.is_negative_case,
            )
            fallback_eval = EvalResult(
                scenario_id=entry.id,
                level=entry.level,
                is_correct=False,
                match_type="incorrect",
                details=f"Workflow crashed: {exc}",
                telemetry=fallback_tel,
            )
            _persist_telemetry(fallback_tel)
            workflow_telemetries.append(fallback_tel)
            workflow_evals.append(fallback_eval)

        result = ScenarioResult(
            entry=entry,
            agent_eval=agent_evals[-1],
            workflow_eval=workflow_evals[-1],
            agent_telemetry=agent_telemetries[-1],
            workflow_telemetry=workflow_telemetries[-1],
        )
        output.scenario_results.append(result)

    output.agent_metrics = _compute_metrics(agent_telemetries, agent_evals, "agent")
    output.workflow_metrics = _compute_metrics(workflow_telemetries, workflow_evals, "workflow")

    return output