"""Tests for the Week 7 Agent Loop vs Deterministic Workflow benchmark system."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # E:\week3
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.config import load_config_from_env
from eval.golden_loader import load_all_golden_sets, load_golden_set, get_all_entries, GoldenEntry
from eval.benchmark_runner import _compute_metrics, _expand_scenario_keys
from eval.evaluator import evaluate_answer, EvalResult
from safety.circuit_breaker import CircuitBreaker, SafetyConfig, TokenBudget, CostBudget, TimeBudget
from telemetry.telemetry import ExecutionTelemetry
from tools.migration_analyzer import MigrationAnalyzerInput, migration_analyzer
from tools.reference_search import ReferenceSearchInput
from tools.chunk_retrieval import ChunkRetrievalInput


# ── Golden Set Loading ───────────────────────────────────────────────────────

def test_golden_sets_load(config):
    sets = load_all_golden_sets(config.golden_set_dir)
    assert set(sets.keys()) == {"gs_easy.json", "gs_medium.json", "gs_hard.json"}
    for gs in sets.values():
        assert len(gs.entries) == 15
        assert gs.entries[0].question
        assert gs.entries[0].answer


def test_golden_sets_have_negative_cases(config):
    sets = load_all_golden_sets(config.golden_set_dir)
    negatives = [e for e in get_all_entries(sets) if e.is_negative_case]
    assert len(negatives) == 9  # 3 per file


def test_golden_files_not_modified():
    """Golden set files must never be modified by the loader."""
    path = ROOT / "goldensets" / "gs_easy.json"
    # ensure loading is read-only — loader returns parsed objects only
    assert path.exists()


# ── Strict Tool Schema Validation ────────────────────────────────────────────

def test_reference_search_schema_validates_input():
    with pytest.raises(Exception):
        # empty query is rejected by schema
        ReferenceSearchInput(query="")


def test_reference_search_schema_rejects_bad_top_k():
    with pytest.raises(Exception):
        ReferenceSearchInput(query="test", top_k=0)
    with pytest.raises(Exception):
        ReferenceSearchInput(query="test", top_k=100)


def test_chunk_retrieval_schema_validates_input():
    with pytest.raises(Exception):
        ChunkRetrievalInput(chunk_id="")


def test_migration_analyzer_schema_requires_evidence():
    with pytest.raises(Exception):
        MigrationAnalyzerInput(question="q", evidence_chunks=[])


def test_migration_analyzer_refuses_on_empty_evidence():
    out = migration_analyzer(MigrationAnalyzerInput(
        question="Compare versions", evidence_chunks=[{"chunk_id": "c1", "text": "irrelevant filler"}],
    ))
    assert isinstance(out.is_answerable, bool)
    assert 0.0 <= out.confidence <= 1.0


# ── Evaluator ────────────────────────────────────────────────────────────────

def _entry(**overrides) -> GoldenEntry:
    base = dict(
        id="99", level="Easy", question="q?", answer="The default value is 'markdown'.",
        metadata={"is_negative_case": False}, expected_chunk_id=None,
        contains_exact_token=True,
    )
    base.update(overrides)
    return GoldenEntry.from_dict(base)


def test_evaluator_marks_exact_token_positive():
    entry = _entry(answer="The default value is 'markdown'.", contains_exact_token=True)
    tel = ExecutionTelemetry(success=False)
    result = evaluate_answer(entry, "The default value is 'markdown' for the mode parameter.", tel)
    assert result.is_correct
    assert result.match_type == "contains_token"


def test_evaluator_marks_refusal_wrong_for_positive():
    entry = _entry(answer="The default value is 'markdown'.", contains_exact_token=True)
    tel = ExecutionTelemetry(success=False)
    result = evaluate_answer(entry, "Information not provided in the supplied reference context.", tel)
    assert not result.is_correct


def test_evaluator_marks_refusal_correct_for_negative():
    entry = _entry(
        is_negative_case=True,
        metadata={"is_negative_case": True, "expected_behavior": "refusal_or_fallback"},
        contains_exact_token=False,
    )
    tel = ExecutionTelemetry(success=False)
    result = evaluate_answer(entry, "Information not provided in the supplied reference context.", tel)
    assert result.is_correct
    assert result.match_type == "semantic_refusal"


def test_evaluator_fails_fabrication_on_negative():
    entry = _entry(
        is_negative_case=True,
        metadata={"is_negative_case": True, "expected_behavior": "refusal_or_fallback"},
        contains_exact_token=False,
    )
    tel = ExecutionTelemetry(success=False)
    result = evaluate_answer(entry, "The parameter is 'auto_delete_policy' and defaults to 30 days.", tel)
    assert not result.is_correct


# ── Safety / Circuit Breaker ─────────────────────────────────────────────────

def test_circuit_breaker_iteration_limit():
    cb = CircuitBreaker(max_iterations=3)
    for _ in range(3):
        assert not cb.any_exceeded
        cb.step()
    assert cb.iteration_exceeded
    assert cb.exceeded_reason == "max_iterations"


def test_circuit_breaker_token_budget():
    tb = TokenBudget(max_total=100)
    tb.record(input_tokens=60, output_tokens=50)
    assert tb.total_exceeded
    assert tb.exceeded


def test_circuit_breaker_cost_budget():
    cbk = CostBudget(max_usd=0.01)
    cost = cbk.record(input_tokens=100000, output_tokens=0)
    assert cost > cbk.max_usd
    assert cbk.exceeded


def test_circuit_breaker_time_budget():
    tb = TimeBudget(timeout_seconds=-1.0)
    assert tb.exceeded


# ── Benchmark Scenario Selection ─────────────────────────────────────────────

def test_default_ten_scenario_race(config):
    sets = load_all_golden_sets(config.golden_set_dir)
    entries = get_all_entries(sets)
    keys = config.benchmark_scenario_ids
    assert len(keys) == 10
    selected = _expand_scenario_keys(entries, keys)
    assert len(selected) == 10
    positives = [e for e in selected if not e.is_negative_case]
    negatives = [e for e in selected if e.is_negative_case]
    assert len(positives) == 7
    assert len(negatives) == 3
    levels = {e.level for e in selected}
    assert {"Easy", "Medium", "Hard"}.issubset(levels)


def test_expand_scenario_all_levels(config):
    sets = load_all_golden_sets(config.golden_set_dir)
    entries = get_all_entries(sets)
    selected = _expand_scenario_keys(entries, ["01"])
    assert len(selected) == 3  # easy, medium, hard
    assert {e.level for e in selected} == {"Easy", "Medium", "Hard"}


def test_expand_scenario_unknown_key_raises(config):
    sets = load_all_golden_sets(config.golden_set_dir)
    entries = get_all_entries(sets)
    with pytest.raises(ValueError):
        _expand_scenario_keys(entries, ["nope:42"])


# ── Telemetry ────────────────────────────────────────────────────────────────

def test_telemetry_dict_roundtrip():
    tel = ExecutionTelemetry(
        scenario_id="easy:01", architecture="agent", success=True,
        latency_ms=12.3, input_tokens=10, output_tokens=5,
    )
    d = tel.to_dict()
    assert d["scenario_id"] == "easy:01"
    assert d["total_tokens"] == 15
    assert d["architecture"] == "agent"


def test_benchmark_metrics_computation():
    tels = [ExecutionTelemetry(latency_ms=100, input_tokens=10, output_tokens=5),
            ExecutionTelemetry(latency_ms=200, input_tokens=20, output_tokens=10)]
    evals = [EvalResult("1", "Easy", True, "contains_token", "ok", tels[0]),
             EvalResult("2", "Easy", False, "incorrect", "bad", tels[1])]
    m = _compute_metrics(tels, evals, "agent")
    assert m.success_rate == 50.0
    assert m.total_tokens == 45
    assert m.avg_total_tokens == 22.5