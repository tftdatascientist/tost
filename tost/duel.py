"""Duel engine — two CC profiles face off on token cost."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy

from tost.simulator import (
    Component, SimConfig, MessageSim, build_components,
    DEFAULT_FULL_COMPONENTS, DEFAULT_MINIMAL_COMPONENTS, DEFAULT_TOOL_PROFILES,
    ToolUsage, _get_rates, _per_message_overhead, _session_start_overhead,
)


# ── Profile presets ─────────────────────────────────────────────────────────

@dataclass
class Profile:
    """A named CC configuration profile for duel comparison."""
    name: str
    description: str
    model: str
    components: list[Component]

    @property
    def session_tokens(self) -> int:
        return _session_start_overhead(self.components)

    @property
    def per_message_tokens(self) -> int:
        return _per_message_overhead(self.components)

    @property
    def total_config_tokens(self) -> int:
        return self.session_tokens + self.per_message_tokens


# Preset profiles representing common real-world configurations

PRESET_PROFILES: list[dict] = [
    {
        "name": "Power User",
        "description": "All plugins, memory, MCP, skills — maximum context",
        "model": "claude-opus-4",
        "component_names": None,  # None = all DEFAULT_FULL_COMPONENTS
    },
    {
        "name": "Minimalist",
        "description": "Base system prompt only — zero extras",
        "model": "claude-sonnet-4",
        "component_names": None,  # uses DEFAULT_MINIMAL_COMPONENTS
        "_minimal": True,
    },
    {
        "name": "Developer",
        "description": "Base + CLAUDE.md + Git + deferred tools — lean dev setup",
        "model": "claude-sonnet-4",
        "component_names": [
            ("System prompt (base)", "session_start"),
            ("Hooks definitions", "session_start"),
            ("System prompt (base)", "per_message"),
            ("Global CLAUDE.md", "per_message"),
            ("Git status context", "per_message"),
            ("Deferred tools catalog", "per_message"),
        ],
    },
    {
        "name": "Team Lead",
        "description": "Base + code-review + CLAUDE.md mgmt + memory",
        "model": "claude-opus-4",
        "component_names": [
            ("System prompt (base)", "session_start"),
            ("Plugin: code-review", "session_start"),
            ("Plugin: claude-md-management", "session_start"),
            ("System prompt (base)", "per_message"),
            ("Global CLAUDE.md", "per_message"),
            ("Project memory (MEMORY.md + files)", "per_message"),
            ("Git status context", "per_message"),
            ("Auto-memory instructions", "per_message"),
        ],
    },
    {
        "name": "Frontend Dev",
        "description": "Base + Vercel + frontend-design + skills",
        "model": "claude-sonnet-4",
        "component_names": [
            ("System prompt (base)", "session_start"),
            ("Skills catalog", "session_start"),
            ("Plugin: vercel", "session_start"),
            ("Plugin: frontend-design", "session_start"),
            ("System prompt (base)", "per_message"),
            ("Global CLAUDE.md", "per_message"),
            ("Git status context", "per_message"),
            ("Skills reminder", "per_message"),
            ("Deferred tools catalog", "per_message"),
        ],
    },
    {
        "name": "Full Stack + MCP",
        "description": "All plugins + MCP tools + memory — heavy integration",
        "model": "claude-opus-4",
        "component_names": [
            ("System prompt (base)", "session_start"),
            ("Skills catalog", "session_start"),
            ("Plugin: superpowers", "session_start"),
            ("Plugin: vercel", "session_start"),
            ("Plugin: frontend-design", "session_start"),
            ("Plugin: code-review", "session_start"),
            ("Plugin: claude-md-management", "session_start"),
            ("Hooks definitions", "session_start"),
            ("System prompt (base)", "per_message"),
            ("Global CLAUDE.md", "per_message"),
            ("Project memory (MEMORY.md + files)", "per_message"),
            ("MCP tool descriptions", "per_message"),
            ("Deferred tools catalog", "per_message"),
            ("Git status context", "per_message"),
            ("Skills reminder", "per_message"),
            ("Auto-memory instructions", "per_message"),
        ],
    },
]


def build_profile(preset: dict) -> Profile:
    """Build a Profile from a preset dict."""
    if preset.get("_minimal"):
        components = build_components(DEFAULT_MINIMAL_COMPONENTS)
    elif preset["component_names"] is None:
        components = build_components(DEFAULT_FULL_COMPONENTS)
    else:
        all_comps = build_components(DEFAULT_FULL_COMPONENTS)
        enabled_keys = {(n, c) for n, c in preset["component_names"]}
        components = []
        for comp in all_comps:
            if (comp.name, comp.category) in enabled_keys:
                components.append(comp)
    return Profile(
        name=preset["name"],
        description=preset["description"],
        model=preset["model"],
        components=components,
    )


def get_preset_profiles() -> list[Profile]:
    """Return all preset profiles."""
    return [build_profile(p) for p in PRESET_PROFILES]


# ── Duel simulation ────────────────────────────────────────────────────────

@dataclass
class DuelMessageSim:
    """Per-message duel comparison."""
    msg_number: int
    context_tokens: int
    # Profile A
    input_a: int
    output_a: int
    cost_a: float
    cumulative_a: float
    # Profile B
    input_b: int
    output_b: int
    cost_b: float
    cumulative_b: float
    # Delta
    cost_delta: float       # positive = A costs more
    cumulative_delta: float


@dataclass
class DuelResult:
    """Complete duel result."""
    profile_a: Profile
    profile_b: Profile
    config: SimConfig
    messages: list[DuelMessageSim]
    total_cost_a: float
    total_cost_b: float
    winner: str              # name of cheaper profile
    savings: float           # absolute savings
    savings_pct: float       # percentage savings


def run_duel(
    profile_a: Profile,
    profile_b: Profile,
    cfg: SimConfig | None = None,
) -> DuelResult:
    """Run a head-to-head duel between two profiles."""
    if cfg is None:
        cfg = SimConfig()

    # Override model from config — each profile uses its own model for pricing
    rates_a = _get_rates(profile_a.model)
    rates_b = _get_rates(profile_b.model)

    a_per_msg = profile_a.per_message_tokens
    b_per_msg = profile_b.per_message_tokens
    a_session = profile_a.session_tokens
    b_session = profile_b.session_tokens

    tool_profiles = [ToolUsage(**t) for t in DEFAULT_TOOL_PROFILES]
    avg_tool_in = sum(t.avg_input_tokens for t in tool_profiles) // len(tool_profiles)
    avg_tool_out = sum(t.avg_output_tokens for t in tool_profiles) // len(tool_profiles)

    messages: list[DuelMessageSim] = []
    accumulated_context = 0.0
    cum_a = a_session * rates_a["input"]  # session start cost
    cum_b = b_session * rates_b["input"]

    for i in range(1, cfg.num_messages + 1):
        num_tools = round(cfg.tools_per_message)
        tool_in = avg_tool_in * num_tools
        tool_out = avg_tool_out * num_tools

        context_tokens = int(accumulated_context)
        cached_context = int(context_tokens * cfg.cache_hit_rate)
        uncached_context = context_tokens - cached_context

        # Profile A
        input_a = a_per_msg + cfg.avg_user_tokens + uncached_context + tool_in
        cached_a = cached_context
        output_a = cfg.avg_assistant_tokens + tool_out
        cost_a = (
            input_a * rates_a["input"]
            + cached_a * rates_a["cache_read"]
            + output_a * rates_a["output"]
        )

        # Profile B
        input_b = b_per_msg + cfg.avg_user_tokens + uncached_context + tool_in
        cached_b = cached_context
        output_b = cfg.avg_assistant_tokens + tool_out
        cost_b = (
            input_b * rates_b["input"]
            + cached_b * rates_b["cache_read"]
            + output_b * rates_b["output"]
        )

        cum_a += cost_a
        cum_b += cost_b

        messages.append(DuelMessageSim(
            msg_number=i,
            context_tokens=context_tokens,
            input_a=input_a + cached_a,
            output_a=output_a,
            cost_a=cost_a,
            cumulative_a=cum_a,
            input_b=input_b + cached_b,
            output_b=output_b,
            cost_b=cost_b,
            cumulative_b=cum_b,
            cost_delta=cost_a - cost_b,
            cumulative_delta=cum_a - cum_b,
        ))

        new_tokens = cfg.avg_user_tokens + cfg.avg_assistant_tokens + tool_in + tool_out
        accumulated_context = (accumulated_context + new_tokens) * cfg.context_growth_rate

    total_a = cum_a
    total_b = cum_b

    if total_a <= total_b:
        winner = profile_a.name
        savings = total_b - total_a
    else:
        winner = profile_b.name
        savings = total_a - total_b

    max_cost = max(total_a, total_b)
    savings_pct = (savings / max_cost * 100) if max_cost > 0 else 0

    return DuelResult(
        profile_a=profile_a,
        profile_b=profile_b,
        config=cfg,
        messages=messages,
        total_cost_a=total_a,
        total_cost_b=total_b,
        winner=winner,
        savings=savings,
        savings_pct=savings_pct,
    )
