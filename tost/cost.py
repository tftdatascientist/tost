"""Anthropic pricing tables and cost calculator."""

from __future__ import annotations

# Prices in USD per 1M tokens
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_creation": 18.75,
    },
    "claude-sonnet-4": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "claude-haiku-4": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_creation": 1.0,
    },
}


def resolve_model(model_name: str) -> dict[str, float] | None:
    """Match a model string like 'claude-sonnet-4-6' to its pricing tier."""
    for prefix, rates in PRICING.items():
        if model_name.startswith(prefix):
            return rates
    # Fallback: try matching without version suffix
    for prefix, rates in PRICING.items():
        if prefix in model_name:
            return rates
    return None


def calculate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Calculate cost in USD for given token counts."""
    rates = resolve_model(model)
    if not rates:
        return 0.0
    return (
        input_tokens * rates["input"]
        + output_tokens * rates["output"]
        + cache_read_tokens * rates["cache_read"]
        + cache_creation_tokens * rates["cache_creation"]
    ) / 1_000_000


def format_cost(usd: float) -> str:
    """Format cost as human-readable string."""
    if usd < 0.001:
        return f"${usd:.6f}"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"
