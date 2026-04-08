"""Cost simulation engine — compare full CC vs minimal CC configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Component definitions ────────────────────────────────────────────────────

@dataclass
class Component:
    """A single CC configuration component contributing to token overhead."""
    name: str
    category: str  # "session_start" or "per_message"
    tokens: int
    description: str
    enabled: bool = True


# Default components based on measured real-world CC configuration
DEFAULT_FULL_COMPONENTS: list[dict] = [
    # ── Session start (injected once) ──
    {
        "name": "System prompt (base)",
        "category": "session_start",
        "tokens": 4500,
        "description": "Core CC system prompt — instructions, tools, tone, safety rules",
    },
    {
        "name": "Skills catalog",
        "category": "session_start",
        "tokens": 5200,
        "description": "Skill descriptions injected into context (superpowers, vercel, frontend-design, etc.)",
    },
    {
        "name": "Plugin: superpowers",
        "category": "session_start",
        "tokens": 3800,
        "description": "Brainstorming, TDD, debugging, plan workflows, code review skills",
    },
    {
        "name": "Plugin: vercel",
        "category": "session_start",
        "tokens": 2400,
        "description": "Vercel knowledge updates, deployment, AI SDK, Next.js guidance",
    },
    {
        "name": "Plugin: frontend-design",
        "category": "session_start",
        "tokens": 1200,
        "description": "Frontend design patterns and component guidance",
    },
    {
        "name": "Plugin: code-review",
        "category": "session_start",
        "tokens": 800,
        "description": "Code review agent and workflows",
    },
    {
        "name": "Plugin: claude-md-management",
        "category": "session_start",
        "tokens": 600,
        "description": "CLAUDE.md audit and improvement tools",
    },
    {
        "name": "Hooks definitions",
        "category": "session_start",
        "tokens": 460,
        "description": "Hook event handlers from settings.json",
    },
    # ── Per message (injected every turn) ──
    {
        "name": "System prompt (base)",
        "category": "per_message",
        "tokens": 4500,
        "description": "Core CC system prompt — re-sent with every message",
    },
    {
        "name": "Global CLAUDE.md",
        "category": "per_message",
        "tokens": 20,
        "description": "User's global instructions (~73 chars)",
    },
    {
        "name": "Project memory (MEMORY.md + files)",
        "category": "per_message",
        "tokens": 1900,
        "description": "Active project memory index + referenced memory files",
    },
    {
        "name": "MCP tool descriptions",
        "category": "per_message",
        "tokens": 350,
        "description": "Available MCP server tools (Vercel, Notion, WordPress, Stitch)",
    },
    {
        "name": "Deferred tools catalog",
        "category": "per_message",
        "tokens": 800,
        "description": "List of deferred tools available via ToolSearch",
    },
    {
        "name": "Git status context",
        "category": "per_message",
        "tokens": 500,
        "description": "Git status snapshot injected at session start, re-sent per message",
    },
    {
        "name": "Skills reminder",
        "category": "per_message",
        "tokens": 1200,
        "description": "Available skills list re-injected in system reminders",
    },
    {
        "name": "Auto-memory instructions",
        "category": "per_message",
        "tokens": 2800,
        "description": "Full auto-memory system prompt (types, rules, when to save/access)",
    },
]

# Minimal CC: just the base system prompt, no plugins/memory/MCP
DEFAULT_MINIMAL_COMPONENTS: list[dict] = [
    {
        "name": "System prompt (base)",
        "category": "session_start",
        "tokens": 4500,
        "description": "Core CC system prompt — always present",
    },
    {
        "name": "System prompt (base)",
        "category": "per_message",
        "tokens": 4500,
        "description": "Core CC system prompt — re-sent with every message",
    },
]


# ── Tool usage profiles ─────────────────────────────────────────────────────

@dataclass
class ToolUsage:
    """Estimated token cost of using a specific tool."""
    name: str
    avg_input_tokens: int   # tokens added to input per use
    avg_output_tokens: int  # tokens in response per use
    description: str


DEFAULT_TOOL_PROFILES: list[dict] = [
    {"name": "Read file", "avg_input_tokens": 800, "avg_output_tokens": 50, "description": "Read a file (avg ~200 lines)"},
    {"name": "Edit file", "avg_input_tokens": 300, "avg_output_tokens": 100, "description": "Edit an existing file"},
    {"name": "Write file", "avg_input_tokens": 200, "avg_output_tokens": 500, "description": "Create a new file"},
    {"name": "Bash command", "avg_input_tokens": 150, "avg_output_tokens": 300, "description": "Run a shell command"},
    {"name": "Grep/Glob", "avg_input_tokens": 100, "avg_output_tokens": 200, "description": "Search files by pattern"},
    {"name": "Agent (subagent)", "avg_input_tokens": 500, "avg_output_tokens": 2000, "description": "Launch a sub-agent"},
    {"name": "Web search/fetch", "avg_input_tokens": 200, "avg_output_tokens": 1500, "description": "Web search or fetch"},
    {"name": "Skill invocation", "avg_input_tokens": 1500, "avg_output_tokens": 300, "description": "Load and execute a skill"},
    {"name": "MCP tool call", "avg_input_tokens": 400, "avg_output_tokens": 600, "description": "Call an MCP server tool"},
]


# ── Simulation engine ────────────────────────────────────────────────────────

@dataclass
class MessageSim:
    """Simulation of a single message exchange."""
    msg_number: int
    user_input_tokens: int
    assistant_output_tokens: int
    context_tokens: int       # accumulated context window
    overhead_tokens: int      # overhead from config (per-message components)
    tool_tokens_in: int       # additional input from tool results
    tool_tokens_out: int      # additional output for tool calls
    total_input: int
    total_output: int
    cost_full: float
    cost_minimal: float
    cost_delta: float
    cumulative_cost_full: float
    cumulative_cost_minimal: float


@dataclass
class SimConfig:
    """Parameters for a simulation run."""
    num_messages: int = 20
    avg_user_tokens: int = 200
    avg_assistant_tokens: int = 800
    tools_per_message: float = 1.5     # average tool uses per message
    context_growth_rate: float = 0.85  # how much of each exchange stays in context
    cache_hit_rate: float = 0.70       # fraction of context served from cache
    model: str = "claude-opus-4"


@dataclass
class SimResult:
    """Complete simulation result."""
    config: SimConfig
    full_components: list[Component]
    minimal_components: list[Component]
    messages: list[MessageSim]
    total_cost_full: float
    total_cost_minimal: float
    total_overhead: float
    overhead_pct: float


def build_components(raw: list[dict]) -> list[Component]:
    """Build Component list from raw dicts."""
    return [Component(**r) for r in raw]


def _get_rates(model: str) -> dict[str, float]:
    """Get per-token rates for a model (USD per token, not per 1M)."""
    from tost.cost import PRICING, resolve_model
    rates = resolve_model(model)
    if not rates:
        rates = PRICING["claude-opus-4"]
    return {k: v / 1_000_000 for k, v in rates.items()}


def _per_message_overhead(components: list[Component]) -> int:
    """Sum tokens from per_message components."""
    return sum(c.tokens for c in components if c.category == "per_message" and c.enabled)


def _session_start_overhead(components: list[Component]) -> int:
    """Sum tokens from session_start components."""
    return sum(c.tokens for c in components if c.category == "session_start" and c.enabled)


def run_simulation(
    cfg: SimConfig,
    full_components: list[Component] | None = None,
    minimal_components: list[Component] | None = None,
    tool_profiles: list[ToolUsage] | None = None,
) -> SimResult:
    """Run a cost simulation comparing full vs minimal CC over N messages."""
    if full_components is None:
        full_components = build_components(DEFAULT_FULL_COMPONENTS)
    if minimal_components is None:
        minimal_components = build_components(DEFAULT_MINIMAL_COMPONENTS)

    if tool_profiles is None:
        tool_profiles = [ToolUsage(**t) for t in DEFAULT_TOOL_PROFILES]

    rates = _get_rates(cfg.model)

    full_per_msg = _per_message_overhead(full_components)
    min_per_msg = _per_message_overhead(minimal_components)
    full_session = _session_start_overhead(full_components)
    min_session = _session_start_overhead(minimal_components)

    # Average tool cost per use (weighted across all tool types)
    if tool_profiles:
        avg_tool_in = sum(t.avg_input_tokens for t in tool_profiles) // len(tool_profiles)
        avg_tool_out = sum(t.avg_output_tokens for t in tool_profiles) // len(tool_profiles)
    else:
        avg_tool_in = avg_tool_out = 0

    messages: list[MessageSim] = []
    accumulated_context = 0.0
    cum_full = 0.0
    cum_min = 0.0

    # Session start cost (first message includes session overhead)
    session_cost_full = (full_session * rates["input"])
    session_cost_min = (min_session * rates["input"])
    cum_full += session_cost_full
    cum_min += session_cost_min

    for i in range(1, cfg.num_messages + 1):
        # Tool usage for this message
        num_tools = round(cfg.tools_per_message)
        tool_in = avg_tool_in * num_tools
        tool_out = avg_tool_out * num_tools

        # Context grows with each message (previous turns stay in window)
        context_tokens = int(accumulated_context)

        # Cache: portion of context served from cache (cheaper)
        cached_context = int(context_tokens * cfg.cache_hit_rate)
        uncached_context = context_tokens - cached_context

        # ── Full config ──
        total_input_full = (
            full_per_msg          # system overhead per message
            + cfg.avg_user_tokens # user's actual prompt
            + uncached_context    # previous context (not cached)
            + tool_in             # tool result tokens
        )
        cached_input_full = cached_context
        total_output_full = cfg.avg_assistant_tokens + tool_out

        cost_full = (
            total_input_full * rates["input"]
            + cached_input_full * rates["cache_read"]
            + total_output_full * rates["output"]
        )

        # ── Minimal config ──
        total_input_min = (
            min_per_msg
            + cfg.avg_user_tokens
            + uncached_context
            + tool_in
        )
        cached_input_min = cached_context
        total_output_min = cfg.avg_assistant_tokens + tool_out

        cost_min = (
            total_input_min * rates["input"]
            + cached_input_min * rates["cache_read"]
            + total_output_min * rates["output"]
        )

        cum_full += cost_full
        cum_min += cost_min

        messages.append(MessageSim(
            msg_number=i,
            user_input_tokens=cfg.avg_user_tokens,
            assistant_output_tokens=cfg.avg_assistant_tokens,
            context_tokens=context_tokens,
            overhead_tokens=full_per_msg - min_per_msg,
            tool_tokens_in=tool_in,
            tool_tokens_out=tool_out,
            total_input=total_input_full + cached_input_full,
            total_output=total_output_full,
            cost_full=cost_full,
            cost_minimal=cost_min,
            cost_delta=cost_full - cost_min,
            cumulative_cost_full=cum_full,
            cumulative_cost_minimal=cum_min,
        ))

        # Grow accumulated context
        new_tokens = cfg.avg_user_tokens + cfg.avg_assistant_tokens + tool_in + tool_out
        accumulated_context = (accumulated_context + new_tokens) * cfg.context_growth_rate

    total_full = cum_full
    total_min = cum_min
    overhead_pct = ((total_full / total_min) - 1) * 100 if total_min > 0 else 0

    return SimResult(
        config=cfg,
        full_components=full_components,
        minimal_components=minimal_components,
        messages=messages,
        total_cost_full=total_full,
        total_cost_minimal=total_min,
        total_overhead=total_full - total_min,
        overhead_pct=overhead_pct,
    )
