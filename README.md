# TOST — Token Overhead Surveillance Tool

Monitor Claude Code token usage in real-time via OpenTelemetry. See exactly how much your configuration (CLAUDE.md, memory, hooks, plugins) costs in tokens and dollars — and how that overhead grows over a conversation.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## What it does

TOST runs as a standalone process alongside Claude Code. It:

- **Collects** OTLP metrics exported natively by Claude Code (token counts, costs)
- **Stores** every data point in SQLite for full session history
- **Displays** a live TUI dashboard with token breakdown, costs, and growth rate
- **Estimates overhead** — compares your actual token usage against a configurable "minimal" baseline (CC with no plugins, no memory, no CLAUDE.md)

```
┌──────────────────────────────────────────────────┐
│ TOST - Token Overhead Surveillance Tool   [Quit] │
├──────────────────────────────────────────────────┤
│ Session: abc123...  │  Model: opus-4              │
├──────────────────────────────────────────────────┤
│ CURRENT SESSION                                   │
│   Input:     12,450 tok   ($0.037)                │
│   Output:     3,200 tok   ($0.048)                │
│   Cache R:    8,100 tok                           │
│   Cache C:    1,500 tok                           │
│   ────────────────────────────────                │
│   Total cost:               $0.093                │
├──────────────────────────────────────────────────┤
│ BASELINE DELTA                                    │
│   Last msg:  +2,100 tok (+42% overhead)           │
│   Cumul:     +8,450 tok (+35% overhead)           │
├──────────────────────────────────────────────────┤
│ MESSAGES (last 10)                                │
│  #  Time   In     Out    Cache   Cost    Delta    │
│  1  14:02  3100   800    2100   $0.021  +1,200    │
│  2  14:03  4200   1200   3000   $0.035  +2,100    │
└──────────────────────────────────────────────────┘
```

## How it works

```
Claude Code ──OTLP/HTTP──> TOST Collector (:4318) ──> SQLite ──> TUI Dashboard
```

Claude Code natively exports OpenTelemetry metrics every ~5 seconds:
- `claude_code.token.usage` — input, output, cache read, cache creation tokens
- `claude_code.cost.usage` — cumulative cost in USD

TOST receives these via a lightweight HTTP endpoint, computes per-message deltas, and renders everything in a terminal dashboard.

## Installation

```bash
git clone https://github.com/tftdatascientist/tost.git
cd tost
pip install -e .
```

**Requirements:** Python 3.11+

## Quick start

### One-command launcher (Windows)

```bash
tost-launch.bat
```

This opens the TOST dashboard in a new window and starts Claude Code with OTEL export in the current terminal.

### Manual startup

**Terminal 1** — start TOST:
```bash
tost
```

**Terminal 2** — start Claude Code with OTEL:

```bash
# Bash / Git Bash / WSL
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_METRICS_EXPORTER=otlp
claude
```

```powershell
# PowerShell
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
$env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
$env:OTEL_METRICS_EXPORTER = "otlp"
claude
```

## Configuration

Copy `tost.toml.example` to `tost.toml` and adjust:

```toml
[collector]
host = "0.0.0.0"
port = 4318

[database]
path = "tost.db"

[baseline]
# Estimated tokens per message for a minimal CC session
# (no CLAUDE.md, no memory, no hooks, no plugins)
input_tokens_per_message = 3000
output_tokens_per_message = 100

[display]
refresh_interval = 2.0
```

The **baseline** section defines what a "minimal" Claude Code session would use per message. TOST shows how much more your actual setup costs compared to this baseline.

## Cost Simulator

TOST includes an interactive cost simulator that compares your full CC configuration against a minimal (bare) setup — component by component.

```bash
tost sim
```

### What it shows

**Component breakdown** — every element that adds token overhead, with toggle on/off:

| Component | Tokens/msg | Category |
|-----------|-----------|----------|
| System prompt (base) | 4,500 | per message |
| Auto-memory instructions | 2,800 | per message |
| Project memory | 1,900 | per message |
| Skills reminder | 1,200 | per message |
| Deferred tools catalog | 800 | per message |
| Git status context | 500 | per message |
| MCP tool descriptions | 350 | per message |
| Global CLAUDE.md | 20 | per message |
| Skills catalog | 5,200 | session start |
| Plugin: superpowers | 3,800 | session start |
| Plugin: vercel | 2,400 | session start |
| ...and more | | |

**Simulation parameters** (adjustable in TUI):
- Number of messages (1–100+)
- User/assistant tokens per message
- Tools per message
- Cache hit rate
- Context retention rate
- Model (Opus/Sonnet/Haiku)

**Growth chart** — ASCII visualization of how costs diverge over a conversation, with per-message cost table.

### Example output

With default settings (Opus, 30 messages):
```
Full config:    $4.248
Minimal config: $2.896
Overhead:       $1.352 (+46.7%)
```

## CLI options

```
tost [COMMAND] [OPTIONS]

Commands:
  monitor    Live token monitoring via OTEL (default)
  sim        Interactive cost simulation — full vs minimal CC

Monitor options:
  --config, -c PATH    Path to tost.toml
  --port, -p PORT      OTLP receiver port (default: 4318)
  --session, -s ID     Filter to specific session ID
  --db PATH            SQLite database path
  --no-tui             Run collector only, no dashboard
  --verbose, -v        Verbose logging
```

## Keyboard shortcuts

### Monitor mode

| Key | Action  |
|-----|---------|
| `q` | Quit    |
| `r` | Refresh |

### Simulation mode

| Key | Action |
|-----|--------|
| `q` | Quit |
| `Enter` | Run simulation |
| Click row | Toggle component on/off |

## Pricing reference

Built-in Anthropic pricing (per 1M tokens):

| Model | Input | Output | Cache Read | Cache Creation |
|-------|-------|--------|------------|----------------|
| Opus 4 | $15.00 | $75.00 | $1.50 | $18.75 |
| Sonnet 4 | $3.00 | $15.00 | $0.30 | $3.75 |
| Haiku 4 | $0.80 | $4.00 | $0.08 | $1.00 |

## Project structure

```
tost/
  __init__.py
  __main__.py         # python -m tost
  cli.py              # CLI + subcommands (monitor, sim)
  config.py           # TOML config with defaults
  collector.py        # OTLP HTTP receiver (aiohttp)
  store.py            # SQLite storage (cumulative → delta)
  cost.py             # Anthropic pricing tables
  baseline.py         # Overhead estimation vs minimal baseline
  dashboard.py        # Textual TUI — live monitoring
  simulator.py        # Cost simulation engine
  sim_dashboard.py    # Textual TUI — interactive simulator
```

## License

MIT
