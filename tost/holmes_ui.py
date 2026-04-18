"""Holmes TUI — wybór okresu analizy, wyniki, zapis do Notion."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.widgets import (
    Header, Footer, Label, Button, Input, DataTable,
    Static, LoadingIndicator, Select,
)
from textual.screen import Screen
from textual import work

from tost.holmes import Suspect, _load_rules, run_holmes, push_suspects_to_notion
from tost.jsonl_scanner import scan_all_sessions
from tost.cost import format_cost

log = logging.getLogger("tost.holmes_ui")

SEVERITY_COLOR = {
    "HIGH":   "red",
    "MEDIUM": "yellow",
    "LOW":    "dim",
}


# ── Ekran wyboru okresu ──────────────────────────────────────────────────────


class HolmesSetupScreen(Screen):
    """Formularz: wybór okresu i uruchomienie analizy."""

    CSS = """
    HolmesSetupScreen {
        align: center middle;
    }
    #setup-box {
        width: 70;
        height: auto;
        border: double $warning;
        padding: 1 2;
    }
    #setup-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    #preset-row {
        height: 3;
        margin-top: 1;
    }
    .preset-btn {
        margin-right: 1;
    }
    #btn-run {
        margin-top: 2;
        width: 100%;
    }
    #setup-error {
        color: $error;
        height: 1;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        today = datetime.now(timezone.utc)
        week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        with Vertical(id="setup-box"):
            yield Label("🔍  Holmes — Analiza anomalii tokenów", id="setup-title")

            yield Label("Predefiniowane okresy:", classes="field-label")
            with Horizontal(id="preset-row"):
                yield Button("Dziś",        id="preset-today",   classes="preset-btn", variant="default")
                yield Button("7 dni",       id="preset-7d",      classes="preset-btn", variant="default")
                yield Button("30 dni",      id="preset-30d",     classes="preset-btn", variant="default")
                yield Button("Cały czas",   id="preset-all",     classes="preset-btn", variant="default")

            yield Label("Data od (YYYY-MM-DD):", classes="field-label")
            yield Input(value=week_ago, id="date-from", placeholder="np. 2026-04-01")

            yield Label("Data do (YYYY-MM-DD, puste = dziś):", classes="field-label")
            yield Input(value=today_str, id="date-to", placeholder="np. 2026-04-14")

            yield Label("", id="setup-error")
            yield Button("Uruchom Holmesa ▶", id="btn-run", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        today = datetime.now(timezone.utc)
        today_str = today.strftime("%Y-%m-%d")

        if event.button.id == "preset-today":
            self.query_one("#date-from", Input).value = today_str
            self.query_one("#date-to", Input).value = today_str
        elif event.button.id == "preset-7d":
            self.query_one("#date-from", Input).value = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            self.query_one("#date-to", Input).value = today_str
        elif event.button.id == "preset-30d":
            self.query_one("#date-from", Input).value = (today - timedelta(days=30)).strftime("%Y-%m-%d")
            self.query_one("#date-to", Input).value = today_str
        elif event.button.id == "preset-all":
            self.query_one("#date-from", Input).value = ""
            self.query_one("#date-to", Input).value = ""
        elif event.button.id == "btn-run":
            self._run_analysis()

    def _run_analysis(self) -> None:
        date_from = self.query_one("#date-from", Input).value.strip() or None
        date_to   = self.query_one("#date-to",   Input).value.strip() or None
        err = self.query_one("#setup-error", Label)

        # Walidacja dat
        for val, name in [(date_from, "Data od"), (date_to, "Data do")]:
            if val:
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    err.update(f"Błąd: {name} — nieprawidłowy format (YYYY-MM-DD)")
                    return

        err.update("")
        self.app.push_screen(HolmesResultScreen(date_from=date_from, date_to=date_to))


# ── Ekran wyników ────────────────────────────────────────────────────────────


class HolmesResultScreen(Screen):
    """Wyniki analizy — lista suspects + możliwość zapisu do Notion."""

    CSS = """
    HolmesResultScreen {
        layout: vertical;
    }
    #result-header {
        height: 1;
        padding: 0 2;
        color: $warning;
        text-style: bold;
    }
    #suspects-table {
        height: 1fr;
        border: solid $warning;
    }
    #bottom-bar {
        height: 5;
        border-top: solid $accent;
        padding: 0 2;
        layout: horizontal;
        align: left middle;
    }
    #status-label {
        width: 1fr;
        color: $text-muted;
    }
    #btn-notion {
        margin-left: 1;
    }
    #btn-back {
        margin-left: 1;
    }
    LoadingIndicator {
        height: 3;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Wróć"),
        Binding("n", "push_notion", "Zapisz do Notion"),
    ]

    def __init__(self, date_from: str | None, date_to: str | None) -> None:
        super().__init__()
        self.date_from = date_from
        self.date_to = date_to
        self._suspects: list[Suspect] = []
        self._analysing = True

    def compose(self) -> ComposeResult:
        period = f"{self.date_from or 'początek'} → {self.date_to or 'dziś'}"
        yield Header()
        yield Label(f" Holmes — wyniki  [{period}]", id="result-header")
        yield DataTable(id="suspects-table")
        with Horizontal(id="bottom-bar"):
            yield Label("Analizuję sesje...", id="status-label")
            yield Button("Zapisz do Notion", id="btn-notion", variant="warning", disabled=True)
            yield Button("← Wróć", id="btn-back", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#suspects-table", DataTable)
        table.add_columns(
            "Severity", "Kategoria", "Projekt", "Session ID",
            "Model", "Wiad", "Koszt", "Szczegół",
        )
        table.cursor_type = "row"
        self._do_analysis()

    @work(thread=True)
    def _do_analysis(self) -> None:
        rules = _load_rules()
        sessions = list(scan_all_sessions())
        suspects = run_holmes(sessions, rules, self.date_from, self.date_to)
        self.app.call_from_thread(self._show_results, suspects)

    def _show_results(self, suspects: list[Suspect]) -> None:
        self._suspects = suspects
        self._analysing = False
        table = self.query_one("#suspects-table", DataTable)
        status = self.query_one("#status-label", Label)

        if not suspects:
            status.update("[green]Brak anomalii w wybranym okresie. Czysto![/green]")
            return

        for s in suspects:
            project_short = s.session.project.rstrip("/").rsplit("/", 1)[-1]
            model_short = s.session.primary_model.replace("claude-", "")
            color = SEVERITY_COLOR.get(s.severity, "")
            sev_label = f"[{color}]{s.severity}[/{color}]" if color else s.severity
            table.add_row(
                sev_label,
                s.category,
                project_short[:20],
                s.session.session_id[:12] + "…",
                model_short,
                str(s.session.message_count),
                format_cost(s.session.cost_usd),
                s.detail[:60],
            )

        status.update(
            f"Znaleziono [bold]{len(suspects)}[/bold] podejrzanych sesji. "
            f"Naciśnij [bold]N[/bold] lub przycisk, aby zapisać do Notion."
        )
        self.query_one("#btn-notion", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-notion":
            self.action_push_notion()
        elif event.button.id == "btn-back":
            self.action_go_back()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_push_notion(self) -> None:
        if not self._suspects:
            return
        token = os.environ.get("NOTION_TOKEN")
        db_id = os.environ.get("HOLMES_SUSPECTS_DB_ID") or os.environ.get("NOTION_DATABASE_ID")
        if not token:
            self.query_one("#status-label", Label).update(
                "[red]Błąd: NOTION_TOKEN nie ustawiony[/red]"
            )
            return
        if not db_id:
            self.query_one("#status-label", Label).update(
                "[red]Błąd: HOLMES_SUSPECTS_DB_ID (lub NOTION_DATABASE_ID) nie ustawiony[/red]"
            )
            return
        self.query_one("#btn-notion", Button).disabled = True
        self.query_one("#status-label", Label).update("Zapisuję do Notion...")
        self._do_notion_push(token, db_id)

    @work(thread=True)
    def _do_notion_push(self, token: str, db_id: str) -> None:
        created, failed = asyncio.run(
            push_suspects_to_notion(self._suspects, token, db_id)
        )
        self.app.call_from_thread(self._show_push_result, created, failed)

    def _show_push_result(self, created: int, failed: int) -> None:
        if failed == 0:
            self.query_one("#status-label", Label).update(
                f"[green]✓ Zapisano {created} suspect(ów) do Notion.[/green]"
            )
        else:
            self.query_one("#status-label", Label).update(
                f"[yellow]Zapisano {created}, błędy: {failed}. Sprawdź logi.[/yellow]"
            )


# ── Główna aplikacja Holmes ──────────────────────────────────────────────────


class HolmesApp(App):
    """Holmes — standalone TUI analizatora anomalii."""

    TITLE = "Holmes"
    SUB_TITLE = "TOST Token Anomaly Detector"

    CSS = """
    Screen { background: $background; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.push_screen(HolmesSetupScreen())
