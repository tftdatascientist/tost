"""TOST TUI — wyświetla sesje dokładnie tak jak trafiają do Notion."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, DataTable, Label, Static
from textual.containers import Vertical

from tost.jsonl_scanner import scan_all_sessions, SessionAggregate
from tost.cost import format_cost


REFRESH_INTERVAL = 15.0  # sekundy


def _fmt_ts(iso: str) -> str:
    """Skraca ISO timestamp do HH:MM DD-MM."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d-%m %H:%M")
    except ValueError:
        return iso[:16]


def _short_project(project: str) -> str:
    """Ostatni segment ścieżki projektu."""
    return project.rstrip("/").rsplit("/", 1)[-1] or project


def _short_model(model: str) -> str:
    """claude-sonnet-4-6 → sonnet-4-6"""
    return model.replace("claude-", "")


class SummaryBar(Static):
    """Pasek z podsumowaniem łącznym wszystkich sesji."""

    DEFAULT_CSS = """
    SummaryBar {
        height: 3;
        border: solid $accent;
        padding: 0 2;
        color: $text;
    }
    """

    def update_summary(self, sessions: list[SessionAggregate]) -> None:
        if not sessions:
            self.update("Brak sesji")
            return
        total_cost = sum(s.cost_usd for s in sessions)
        total_in = sum(s.input_tokens for s in sessions)
        total_out = sum(s.output_tokens for s in sessions)
        total_msgs = sum(s.message_count for s in sessions)
        ping_str = self._get_ping_status()
        self.update(
            f"Sesje: {len(sessions)}   |   "
            f"Wiad: {total_msgs:,}   |   "
            f"In: {total_in:,}   Out: {total_out:,}   |   "
            f"Koszt łączny: {format_cost(total_cost)}"
            + ping_str
        )

    @staticmethod
    def _get_ping_status() -> str:
        """Odczytaj ostatni ping z tost_ping.db (jeśli istnieje)."""
        import sqlite3
        db_path = Path.home() / ".claude" / "tost_ping.db"
        if not db_path.exists():
            return ""
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT ttfb_ms, total_ms, status_code, timestamp "
                "FROM ping_raw WHERE target = 'api' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if not row:
                return ""
            ttfb_ms, total_ms, status_code, ts = row
            # Stale check — starsze niż 15 min
            try:
                ping_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - ping_time).total_seconds() / 60
                if age_min > 15:
                    return "   |   Ping: --"
            except ValueError:
                pass
            if status_code and status_code < 500:
                # TTFB = opóźnienie serwera, total = pełny cykl
                if ttfb_ms and ttfb_ms > 0:
                    return f"   |   API: {ttfb_ms:.0f}ms (total {total_ms:.0f}ms)"
                return f"   |   Ping: {total_ms:.0f}ms"
            return "   |   Ping: ERR"
        except Exception:
            return ""


class TostApp(App):
    """TOST — monitor sesji Claude Code."""

    TITLE = "TOST"
    SUB_TITLE = "Token Optimization System Tool"

    CSS = """
    Screen { layout: vertical; }
    #title-bar {
        height: 1;
        padding: 0 2;
        color: $accent;
        text-style: bold;
    }
    #session-table {
        height: 1fr;
        border: solid $accent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Odśwież"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label(" SESJE  (odświeżanie co 15s — R aby teraz)", id="title-bar")
            yield SummaryBar()
            yield DataTable(id="session-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.add_columns(
            "Projekt",
            "Session ID",
            "Model",
            "Start",
            "Ostatnia",
            "Wiad",
            "In tok",
            "Out tok",
            "Cache R",
            "Cache C",
            "Koszt",
        )
        table.cursor_type = "row"
        self.action_refresh()
        self.set_interval(REFRESH_INTERVAL, self.action_refresh)

    def action_refresh(self) -> None:
        sessions = sorted(
            scan_all_sessions(),
            key=lambda s: s.last_message_at or "",
            reverse=True,
        )
        table = self.query_one("#session-table", DataTable)
        table.clear()
        for s in sessions:
            table.add_row(
                _short_project(s.project),
                s.session_id[:12] + "…",
                _short_model(s.primary_model),
                _fmt_ts(s.started_at),
                _fmt_ts(s.last_message_at),
                str(s.message_count),
                f"{s.input_tokens:,}",
                f"{s.output_tokens:,}",
                f"{s.cache_read_tokens:,}",
                f"{s.cache_creation_tokens:,}",
                format_cost(s.cost_usd),
            )
        self.query_one(SummaryBar).update_summary(sessions)
