"""Interactive simulation TUI — compare full vs minimal CC costs."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import (
    Header, Footer, Static, DataTable, Label, Input, Button, Checkbox,
)

from tost.cost import format_cost
from tost.simulator import (
    SimConfig, Component, build_components, run_simulation,
    DEFAULT_FULL_COMPONENTS, DEFAULT_MINIMAL_COMPONENTS, DEFAULT_TOOL_PROFILES,
    ToolUsage,
)


class ParamsPanel(Static):
    """Adjustable simulation parameters."""

    def compose(self) -> ComposeResult:
        yield Label(" SIMULATION PARAMETERS ", classes="panel-title")
        with Horizontal(classes="param-row"):
            yield Label("Messages:      ", classes="param-label")
            yield Input(value="30", id="inp-messages", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("User tok/msg:  ", classes="param-label")
            yield Input(value="200", id="inp-user-tok", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Asst tok/msg:  ", classes="param-label")
            yield Input(value="800", id="inp-asst-tok", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Tools/msg:     ", classes="param-label")
            yield Input(value="1.5", id="inp-tools", type="number", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Cache hit %:   ", classes="param-label")
            yield Input(value="70", id="inp-cache", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Context keep %:", classes="param-label")
            yield Input(value="85", id="inp-context", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Model:         ", classes="param-label")
            yield Input(value="claude-opus-4", id="inp-model", classes="param-input")
        yield Button("Run Simulation", id="btn-run", variant="primary")

    def get_config(self) -> SimConfig:
        return SimConfig(
            num_messages=int(self.query_one("#inp-messages", Input).value or 30),
            avg_user_tokens=int(self.query_one("#inp-user-tok", Input).value or 200),
            avg_assistant_tokens=int(self.query_one("#inp-asst-tok", Input).value or 800),
            tools_per_message=float(self.query_one("#inp-tools", Input).value or 1.5),
            cache_hit_rate=int(self.query_one("#inp-cache", Input).value or 70) / 100,
            context_growth_rate=int(self.query_one("#inp-context", Input).value or 85) / 100,
            model=self.query_one("#inp-model", Input).value or "claude-opus-4",
        )


class ComponentsPanel(Static):
    """Toggle individual CC components on/off."""

    def compose(self) -> ComposeResult:
        yield Label(" COMPONENTS (toggle to disable) ", classes="panel-title")
        yield DataTable(id="comp-table")

    def on_mount(self) -> None:
        table = self.query_one("#comp-table", DataTable)
        table.add_columns("On", "Component", "Category", "Tokens", "Description")
        table.cursor_type = "row"
        self._populate()

    def _populate(self) -> None:
        table = self.query_one("#comp-table", DataTable)
        table.clear()
        components = build_components(DEFAULT_FULL_COMPONENTS)
        for c in components:
            table.add_row(
                "Yes" if c.enabled else " - ",
                c.name,
                c.category.replace("_", " "),
                f"{c.tokens:,}",
                c.description[:50],
                key=c.name + "|" + c.category,
            )

    def get_components(self, disabled_keys: set[str]) -> list[Component]:
        components = build_components(DEFAULT_FULL_COMPONENTS)
        for c in components:
            key = c.name + "|" + c.category
            if key in disabled_keys:
                c.enabled = False
        return components


class SummaryPanel(Static):
    """Shows simulation summary."""

    def compose(self) -> ComposeResult:
        yield Label(" COST COMPARISON SUMMARY ", classes="panel-title")
        yield Label("Run simulation to see results", id="summary-text")


class SimChart(Static):
    """ASCII chart showing cost growth over messages."""

    def compose(self) -> ComposeResult:
        yield Label(" COST GROWTH SIMULATION ", classes="panel-title")
        yield Label("Run simulation to see chart", id="chart-text")


class SimDashboard(App):
    """TOST Simulation Dashboard."""

    TITLE = "TOST"
    SUB_TITLE = "Cost Simulation — Full vs Minimal CC"

    CSS = """
    Screen {
        layout: vertical;
        overflow-y: auto;
    }
    #top-row {
        height: auto;
        max-height: 22;
    }
    ParamsPanel {
        width: 40;
        height: auto;
        border: solid $accent;
        padding: 0 1;
    }
    .param-row {
        height: 3;
    }
    .param-label {
        width: 17;
        padding-top: 1;
    }
    .param-input {
        width: 1fr;
    }
    #btn-run {
        margin: 1 0;
        width: 100%;
    }
    ComponentsPanel {
        width: 1fr;
        height: auto;
        border: solid $accent;
        padding: 0 1;
    }
    #comp-table {
        height: auto;
        max-height: 18;
    }
    SummaryPanel {
        height: auto;
        min-height: 12;
        border: solid $accent;
        padding: 0 1;
    }
    SimChart {
        height: auto;
        min-height: 14;
        border: solid $accent;
        padding: 0 1;
    }
    .panel-title {
        text-style: bold;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "run_sim", "Run"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._disabled_keys: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            with Horizontal(id="top-row"):
                yield ParamsPanel()
                yield ComponentsPanel()
            yield SummaryPanel()
            yield SimChart()
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            self.action_run_sim()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Toggle component enabled/disabled on row click."""
        table = event.data_table
        if table.id != "comp-table":
            return
        key = str(event.row_key.value)
        if key in self._disabled_keys:
            self._disabled_keys.discard(key)
        else:
            self._disabled_keys.add(key)
        # Update the "On" column
        row_data = list(table.get_row(event.row_key))
        row_data[0] = " - " if key in self._disabled_keys else "Yes"
        table.update_cell(event.row_key, table.ordered_columns[0].key, row_data[0])

    def action_run_sim(self) -> None:
        cfg = self.query_one(ParamsPanel).get_config()
        full = self.query_one(ComponentsPanel).get_components(self._disabled_keys)
        minimal = build_components(DEFAULT_MINIMAL_COMPONENTS)

        result = run_simulation(cfg, full, minimal)

        # ── Summary ──
        lines = []
        lines.append(f"  Model: {cfg.model}  |  Messages: {cfg.num_messages}")
        lines.append(f"  User: {cfg.avg_user_tokens} tok/msg  |  Assistant: {cfg.avg_assistant_tokens} tok/msg")
        lines.append(f"  Tools/msg: {cfg.tools_per_message}  |  Cache: {cfg.cache_hit_rate*100:.0f}%")
        lines.append("")

        # Component breakdown
        lines.append("  COMPONENT BREAKDOWN (per message overhead):")
        lines.append(f"  {'Component':<35} {'Tokens':>8}  {'Status'}")
        lines.append(f"  {'─'*60}")
        for c in full:
            if c.category == "per_message":
                status = "ON " if c.enabled else "OFF"
                lines.append(f"  {c.name:<35} {c.tokens:>7,}  [{status}]")
        lines.append(f"  {'─'*60}")

        lines.append("")
        lines.append("  SESSION START OVERHEAD:")
        lines.append(f"  {'Component':<35} {'Tokens':>8}  {'Status'}")
        lines.append(f"  {'─'*60}")
        for c in full:
            if c.category == "session_start":
                status = "ON " if c.enabled else "OFF"
                lines.append(f"  {c.name:<35} {c.tokens:>7,}  [{status}]")
        lines.append(f"  {'─'*60}")

        lines.append("")
        lines.append(f"  TOTAL COST (full):    {format_cost(result.total_cost_full):>12}")
        lines.append(f"  TOTAL COST (minimal): {format_cost(result.total_cost_minimal):>12}")
        lines.append(f"  OVERHEAD:             {format_cost(result.total_overhead):>12}  (+{result.overhead_pct:.1f}%)")

        self.query_one("#summary-text", Label).update("\n".join(lines))

        # ── Chart ──
        chart_lines = self._render_chart(result)
        self.query_one("#chart-text", Label).update("\n".join(chart_lines))

    def _render_chart(self, result) -> list[str]:
        """Render ASCII chart of cost growth."""
        msgs = result.messages
        if not msgs:
            return ["No data"]

        max_cost = msgs[-1].cumulative_cost_full
        if max_cost <= 0:
            return ["Cost too small to chart"]

        chart_width = 60
        chart_height = 10
        lines = []

        # Header
        lines.append(f"  Cost growth over {len(msgs)} messages")
        lines.append(f"  Full: {format_cost(result.total_cost_full)}  |  Minimal: {format_cost(result.total_cost_minimal)}  |  Delta: {format_cost(result.total_overhead)}")
        lines.append("")

        # Scale
        scale_labels = []
        for row in range(chart_height, -1, -1):
            cost_at_row = max_cost * row / chart_height
            scale_labels.append(f"  {format_cost(cost_at_row):>9} │")

        # Build chart rows
        # Sample messages to fit chart_width
        step = max(1, len(msgs) // chart_width)
        sampled = msgs[::step][:chart_width]

        for row_idx, row in enumerate(range(chart_height, -1, -1)):
            threshold = max_cost * row / chart_height
            bar = ""
            for m in sampled:
                if m.cumulative_cost_full >= threshold and m.cumulative_cost_minimal >= threshold:
                    bar += "█"  # both above threshold
                elif m.cumulative_cost_full >= threshold:
                    bar += "▓"  # only full above
                else:
                    bar += " "
            lines.append(f"{scale_labels[row_idx]}{bar}")

        # X axis
        lines.append(f"  {'':>9} └{'─' * len(sampled)}")
        lines.append(f"  {'':>9}  1{'':>{len(sampled)-3}}{len(msgs)}")
        lines.append(f"  {'':>12}Messages →")

        # Legend
        lines.append("")
        lines.append("  █ = Both configs  ▓ = Full only (overhead)")
        lines.append("")

        # Per-message table (first 5, last 5)
        lines.append(f"  {'#':>3}  {'Context':>8}  {'Overhead':>8}  {'Full':>10}  {'Minimal':>10}  {'Delta':>10}  {'Cum Δ':>10}")
        lines.append(f"  {'─'*72}")

        show = []
        if len(msgs) <= 12:
            show = msgs
        else:
            show = msgs[:5] + [None] + msgs[-5:]

        for m in show:
            if m is None:
                lines.append(f"  {'...':>3}")
                continue
            lines.append(
                f"  {m.msg_number:>3}  "
                f"{m.context_tokens:>7,}  "
                f"{m.overhead_tokens:>7,}  "
                f"{format_cost(m.cost_full):>10}  "
                f"{format_cost(m.cost_minimal):>10}  "
                f"{format_cost(m.cost_delta):>10}  "
                f"{format_cost(m.cumulative_cost_full - m.cumulative_cost_minimal):>10}"
            )

        return lines
