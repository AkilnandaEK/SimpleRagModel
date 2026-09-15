"""
telemetry/telemetry.py
------------------------------
Structured telemetry collection for every execution.

Records are persisted into the shared Week 3 trace store (``traces/traces.jsonl``)
via ``app.services.tracing.save_trace``; ``trace_id`` aliases the benchmark
``run_id`` so both systems' records are addressable the same way.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionTelemetry:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    scenario_id: str = ""
    difficulty: str = ""
    architecture: str = ""  # "agent" or "workflow"
    success: bool = False
    expected_behavior: str = ""
    actual_behavior: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    tool_calls: int = 0
    iteration_count: int = 0
    timeout: bool = False
    budget_exceeded: bool = False
    budget_exceeded_reason: str | None = None
    error: str | None = None
    agent_steps: list[dict[str, Any]] | None = None
    tools_selected: list[str] | None = None
    workflow_steps: int = 0
    answer: str = ""
    is_negative_case: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.run_id,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "difficulty": self.difficulty,
            "architecture": self.architecture,
            "success": self.success,
            "expected_behavior": self.expected_behavior,
            "actual_behavior": self.actual_behavior,
            "latency_ms": round(self.latency_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "tool_calls": self.tool_calls,
            "iteration_count": self.iteration_count,
            "timeout": self.timeout,
            "budget_exceeded": self.budget_exceeded,
            "budget_exceeded_reason": self.budget_exceeded_reason,
            "error": self.error,
            "agent_steps": self.agent_steps,
            "tools_selected": self.tools_selected,
            "workflow_steps": self.workflow_steps,
            "answer": self.answer,
            "is_negative_case": self.is_negative_case,
        }


@dataclass
class BenchmarkReport:
    scenarios: int = 0
    agent_results: list[ExecutionTelemetry] = field(default_factory=list)
    workflow_results: list[ExecutionTelemetry] = field(default_factory=list)
    scenario_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenarios": self.scenarios,
            "scenario_ids": self.scenario_ids,
            "agent_results": [r.to_dict() for r in self.agent_results],
            "workflow_results": [r.to_dict() for r in self.workflow_results],
        }