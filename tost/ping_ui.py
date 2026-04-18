"""Ping TUI — podgląd latencji API Anthropic (read-only z tost_ping.db)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Header, Footer, DataTable, Static, Label

from tost.ping import PingState, DEFAULT_PING_DB, DAY_NAMES

REFRESH_INTERVAL = 15.0


class HourlySummary(Static):
    """Tabela godzinowych średnich z ostatnich 7 dni (target=api)."""

    DEFAULT_CSS = """
    HourlySummary {
        height: auto;
        max-height: 14;
        border: solid $accent;
        padding: 0 2;
        color: $text;
    }
    """

    def update_summary(self, hourly: list[dict]) -> None:
        if not hourly:
            self.update("Brak danych do podsumowania godzinowego (target: api, 7 dni)")
            return
        lines = [
            "Godz UTC   TTFB avg  Connect   DNS avg  Total avg  Samples  Err"
        ]
        lines.append("─" * 68)
        for h in hourly:
            lines.append(
                f"  {h['hour']:02d}:00   "
                f"{h['avg_ttfb']:>8.0f}  {h['avg_connect']:>7.0f}  "
                f"{h['avg_dns']:>7.0f}  {h['avg_total']:>9.0f}  "
                f"{h['sample_count']:>7d}  {h['error_count']:>3d}"
            )
        self.update("\n".join(lines))


class PingApp(App):
    """TOST Ping — podgląd latencji API Anthropic."""

    TITLE = "TOST Ping"
    SUB_TITLE = "Anthropic API Latency Monitor"

    CSS = """
    Screen { layout: vertical; }
    #ping-title {
        height: 1;
        padding: 0 2;
        color: $accent;
        text-style: bold;
    }
    #ping-table {
        height: 1fr;
        border: solid $accent;
    }
    #ping-status {
        height: 3;
        border: solid $warning;
        padding: 0 2;
        color: $text;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Odśwież"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label(" PING  (odświeżanie co 15s — R aby teraz)", id="ping-title")
            yield Static("Ładowanie...", id="ping-status")
            yield DataTable(id="ping-table")
            yield HourlySummary()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#ping-table", DataTable)
        table.add_columns(
            "Czas (UTC)", "Target", "TTFB ms", "Connect", "DNS",
            "Total ms", "Status", "Błąd",
        )
        table.cursor_type = "row"
        self.action_refresh()
        self.set_interval(REFRESH_INTERVAL, self.action_refresh)

    def action_refresh(self) -> None:
        db_path = DEFAULT_PING_DB
        if not db_path.exists():
            self.query_one("#ping-status", Static).update(
                "Brak bazy danych — uruchom 'tost ping-collect' aby rozpocząć zbieranie"
            )
            return

        state = PingState(db_path)
        try:
            recent = state.get_recent(50)
            hourly = state.get_hourly_summary(7)
        finally:
            state.close()

        # Status bar — pokaż ostatni pomiar API
        api_last = [p for p in recent if p.target == "api"]
        if api_last:
            last = api_last[0]
            status_text = (
                f"Ostatni API: TTFB {last.ttfb_ms:.0f}ms  "
                f"Total {last.total_ms:.0f}ms  "
                f"(DNS {last.dns_ms:.0f} + Connect {last.connect_ms:.0f} + "
                f"TTFB {last.ttfb_ms:.0f})  "
                f"o {last.timestamp[:19]} UTC"
            )
            if last.error:
                status_text += f"   |   Błąd: {last.error}"
        else:
            status_text = "Brak pomiarów w bazie"
        self.query_one("#ping-status", Static).update(status_text)

        # Tabela ostatnich pomiarów
        table = self.query_one("#ping-table", DataTable)
        table.clear()
        for p in recent:
            table.add_row(
                p.timestamp[:19],
                p.target,
                f"{p.ttfb_ms:.0f}",
                f"{p.connect_ms:.0f}",
                f"{p.dns_ms:.0f}",
                f"{p.total_ms:.0f}",
                str(p.status_code) if p.status_code else "ERR",
                p.error or "—",
            )

        # Podsumowanie godzinowe
        self.query_one(HourlySummary).update_summary(hourly)
