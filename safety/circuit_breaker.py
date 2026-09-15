"""
safety/circuit_breaker.py
-------------------------------
Hard safety boundaries for both agent and workflow architectures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from benchmark.config import SafetyConfig


@dataclass
class TokenBudget:
    input_tokens: int = 0
    output_tokens: int = 0
    max_input: int = 8000
    max_output: int = 2000
    max_total: int = 10000

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def input_exceeded(self) -> bool:
        return self.input_tokens > self.max_input

    @property
    def output_exceeded(self) -> bool:
        return self.output_tokens > self.max_output

    @property
    def total_exceeded(self) -> bool:
        return self.total_tokens > self.max_total

    @property
    def exceeded(self) -> bool:
        return self.input_exceeded or self.output_exceeded or self.total_exceeded

    def record(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


@dataclass
class CostBudget:
    spent_usd: float = 0.0
    max_usd: float = 0.50
    input_cost_per_1k: float = 0.00027
    output_cost_per_1k: float = 0.00027

    @property
    def exceeded(self) -> bool:
        return self.spent_usd > self.max_usd

    def record(self, input_tokens: int = 0, output_tokens: int = 0) -> float:
        cost = (input_tokens / 1000.0) * self.input_cost_per_1k + (output_tokens / 1000.0) * self.output_cost_per_1k
        self.spent_usd += cost
        return cost


@dataclass
class TimeBudget:
    start_time: float = field(default_factory=time.monotonic)
    timeout_seconds: float = 120.0

    @property
    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.start_time) * 1000.0

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def exceeded(self) -> bool:
        return self.elapsed_seconds > self.timeout_seconds


@dataclass
class CircuitBreaker:
    max_iterations: int = 10
    token_budget: TokenBudget = field(default_factory=TokenBudget)
    cost_budget: CostBudget = field(default_factory=CostBudget)
    time_budget: TimeBudget = field(default_factory=TimeBudget)
    iteration_count: int = 0

    @classmethod
    def from_config(cls, cfg: SafetyConfig) -> CircuitBreaker:
        return cls(
            max_iterations=cfg.max_iterations,
            token_budget=TokenBudget(
                max_input=cfg.max_input_tokens,
                max_output=cfg.max_output_tokens,
                max_total=cfg.max_total_tokens,
            ),
            cost_budget=CostBudget(
                max_usd=cfg.max_cost_usd,
            ),
            time_budget=TimeBudget(
                timeout_seconds=cfg.timeout_seconds,
            ),
        )

    @property
    def iteration_exceeded(self) -> bool:
        return self.iteration_count >= self.max_iterations

    @property
    def any_exceeded(self) -> bool:
        return (
            self.iteration_exceeded
            or self.token_budget.exceeded
            or self.cost_budget.exceeded
            or self.time_budget.exceeded
        )

    @property
    def exceeded_reason(self) -> str | None:
        if self.iteration_exceeded:
            return "max_iterations"
        if self.token_budget.exceeded:
            return "token_budget"
        if self.cost_budget.exceeded:
            return "cost_budget"
        if self.time_budget.exceeded:
            return "timeout"
        return None

    def step(self) -> bool:
        """Increment iteration and check if budget allows continuing. Returns True if OK to proceed."""
        self.iteration_count += 1
        return not self.any_exceeded

    def record_tokens(self, input_tokens: int, output_tokens: int) -> float:
        """Record token usage and return cost of this call."""
        self.token_budget.record(input_tokens, output_tokens)
        return self.cost_budget.record(input_tokens, output_tokens)