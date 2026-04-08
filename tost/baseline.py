"""Baseline estimator — compute overhead delta vs minimal CC session."""

from __future__ import annotations

from dataclasses import dataclass

from tost.config import BaselineConfig


@dataclass
class BaselineDelta:
    actual_input: int
    actual_output: int
    baseline_input: int
    baseline_output: int

    @property
    def input_overhead(self) -> int:
        return self.actual_input - self.baseline_input

    @property
    def output_overhead(self) -> int:
        return self.actual_output - self.baseline_output

    @property
    def total_overhead(self) -> int:
        return self.input_overhead + self.output_overhead

    @property
    def overhead_pct(self) -> float:
        baseline_total = self.baseline_input + self.baseline_output
        if baseline_total == 0:
            return 0.0
        return (self.total_overhead / baseline_total) * 100


def compute_message_delta(
    actual_input: int,
    actual_output: int,
    baseline: BaselineConfig,
) -> BaselineDelta:
    """Compute overhead for a single message exchange."""
    return BaselineDelta(
        actual_input=actual_input,
        actual_output=actual_output,
        baseline_input=baseline.input_tokens_per_message,
        baseline_output=baseline.output_tokens_per_message,
    )


def compute_cumulative_delta(
    deltas: list[dict],
    baseline: BaselineConfig,
) -> BaselineDelta:
    """Compute cumulative overhead across all message exchanges."""
    n = len(deltas)
    total_in = sum(d["delta_input"] for d in deltas)
    total_out = sum(d["delta_output"] for d in deltas)
    return BaselineDelta(
        actual_input=total_in,
        actual_output=total_out,
        baseline_input=baseline.input_tokens_per_message * n,
        baseline_output=baseline.output_tokens_per_message * n,
    )
