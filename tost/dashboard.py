"""Textual TUI dashboard for TOST."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, Static, DataTable, Label

from tost.baseline import compute_cumulative_delta, compute_message_delta
from tost.cost import format_cost

if TYPE_CHECKING:
    from tost.config import TostConfig
    from tost.store import Store


class SessionPanel(Static):
    """Shows current session info."""

    def compose(self) -> ComposeResult:
        yield Label("Waiting for data...", id="session-info")


class TokenSummary(Static):
    """Shows token breakdown and cost for current session."""

    def compose(self) -> ComposeResult:
        yield Label("No data yet", id="token-summary")

    def update_data(self, totals: dict | None) -> None:
        label = self.query_one("#token-summary", Label)
        if not totals:
            label.update("No data yet")
            return

        lines = [
            f"  Input:     {totals['input_tokens']:>10,} tok   ({format_cost(0)})",
            f"  Output:    {totals['output_tokens']:>10,} tok   ({format_cost(0)})",
            f"  Cache R:   {totals['cache_read_tokens']:>10,} tok",
            f"  Cache C:   {totals['cache_creation_tokens']:>10,} tok",
            f"  {'─' * 40}",
            f"  Total cost: {format_cost(totals['cost_usd']):>18}",
        ]
        label.update("\n".join(lines))


class BaselinePanel(Static):
    """Shows overhead vs baseline."""

    def compose(self) -> ComposeResult:
        yield Label("No baseline data", id="baseline-info")

    def update_data(self, delta_text: str) -> None:
        self.query_one("#baseline-info", Label).update(delta_text)


class TostApp(App):
    """TOST — Token Overhead Surveillance Tool."""

    TITLE = "TOST"
    SUB_TITLE = "Token Overhead Surveillance Tool"

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-container {
        height: 1fr;
    }
    #left-panel {
        width: 1fr;
        min-width: 44;
    }
    SessionPanel {
        height: 3;
        border: solid $accent;
        padding: 0 1;
    }
    TokenSummary {
        height: 9;
        border: solid $accent;
        padding: 0 1;
    }
    BaselinePanel {
        height: 5;
        border: solid $accent;
        padding: 0 1;
    }
    #message-table {
        height: 1fr;
        border: solid $accent;
    }
    .panel-title {
        text-style: bold;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
    ]

    def __init__(self, store: Store, config: TostConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._config = config
        self._session_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            with Horizontal():
                with Vertical(id="left-panel"):
                    yield Label(" SESSION ", classes="panel-title")
                    yield SessionPanel()
                    yield Label(" TOKENS & COST ", classes="panel-title")
                    yield TokenSummary()
                    yield Label(" BASELINE DELTA ", classes="panel-title")
                    yield BaselinePanel()
            yield Label(" MESSAGES ", classes="panel-title")
            yield DataTable(id="message-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#message-table", DataTable)
        table.add_columns("#", "Time", "In", "Out", "Cache", "Cost", "Delta")
        table.cursor_type = "none"
        self.set_interval(self._config.display.refresh_interval, self.action_refresh_data)

    def action_refresh_data(self) -> None:
        # Determine active session
        session_id = self._session_id or self._store.get_active_session_id()
        if not session_id:
            return

        self._session_id = session_id

        # Update session panel
        totals = self._store.get_session_totals(session_id)
        if totals:
            info = self.query_one("#session-info", Label)
            model = totals.get("model", "?")
            info.update(f"Session: {session_id[:12]}...  |  Model: {model}")

        # Update token summary
        self.query_one(TokenSummary).update_data(totals)

        # Update baseline
        deltas = self._store.get_session_deltas(session_id)
        if deltas:
            last = deltas[-1]
            msg_delta = compute_message_delta(
                last["delta_input"], last["delta_output"],
                self._config.baseline,
            )
            cum_delta = compute_cumulative_delta(deltas, self._config.baseline)

            baseline_text = (
                f"  Last msg:  {msg_delta.total_overhead:+,} tok "
                f"({msg_delta.overhead_pct:+.0f}% overhead)\n"
                f"  Cumul:     {cum_delta.total_overhead:+,} tok "
                f"({cum_delta.overhead_pct:+.0f}% overhead)"
            )
            self.query_one(BaselinePanel).update_data(baseline_text)
        else:
            self.query_one(BaselinePanel).update_data("No messages yet")

        # Update message table
        table = self.query_one("#message-table", DataTable)
        table.clear()
        for i, d in enumerate(deltas[-20:], 1):
            time_str = d["received_at"].split(" ")[-1][:5] if d.get("received_at") else "?"
            total_cache = d["delta_cache_read"] + d["delta_cache_creation"]
            delta_tokens = (
                d["delta_input"] + d["delta_output"]
                - self._config.baseline.input_tokens_per_message
                - self._config.baseline.output_tokens_per_message
            )
            table.add_row(
                str(i),
                time_str,
                f"{d['delta_input']:,}",
                f"{d['delta_output']:,}",
                f"{total_cache:,}",
                format_cost(d["delta_cost"]),
                f"{delta_tokens:+,}",
            )

    def set_session_filter(self, session_id: str) -> None:
        """Filter dashboard to a specific session."""
        self._session_id = session_id
