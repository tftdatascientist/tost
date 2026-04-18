"""Panel terminala Claude Code (cc) — osadzony w TUI obok dashboardu TOST."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from asyncio import subprocess as asubprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, DataTable, Label, Static, Input, RichLog

from tost.jsonl_scanner import scan_all_sessions, SessionAggregate
from tost.cost import format_cost
from tost.dashboard import SummaryBar, _fmt_ts, _short_project, _short_model

REFRESH_INTERVAL = 15.0


class CCTerminalPanel(Vertical):
    """Panel z terminalem Claude Code — Input + RichLog."""

    DEFAULT_CSS = """
    CCTerminalPanel {
        width: 1fr;
        border: solid $warning;
    }
    #cc-title {
        height: 1;
        padding: 0 2;
        color: $warning;
        text-style: bold;
    }
    #cc-log {
        height: 1fr;
    }
    #cc-input {
        height: 3;
        border-top: solid $warning;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(" CC  Claude Code — wpisz prompt i Enter", id="cc-title")
        yield RichLog(id="cc-log", highlight=True, markup=True, wrap=True)
        yield Input(placeholder="Wpisz prompt dla Claude Code...", id="cc-input")

    def on_mount(self) -> None:
        self._proc: asubprocess.Process | None = None
        self._cc_path = shutil.which("cc") or shutil.which("claude")
        if not self._cc_path:
            log = self.query_one("#cc-log", RichLog)
            log.write("[red]Błąd: nie znaleziono polecenia 'cc' ani 'claude' w PATH.[/red]")
            log.write("[dim]Upewnij się, że Claude Code CLI jest zainstalowany.[/dim]")
        else:
            log = self.query_one("#cc-log", RichLog)
            log.write(f"[dim]CC path: {self._cc_path}[/dim]")
            log.write("[green]Gotowy. Wpisz prompt i naciśnij Enter.[/green]")
            log.write("[dim]Skróty: Ctrl+C — przerwij, Ctrl+L — wyczyść log[/dim]")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt:
            return
        input_widget = self.query_one("#cc-input", Input)
        input_widget.value = ""
        await self._run_cc(prompt)

    async def _run_cc(self, prompt: str) -> None:
        log = self.query_one("#cc-log", RichLog)
        if not self._cc_path:
            log.write("[red]Brak CC — nie można uruchomić.[/red]")
            return

        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()
            self._proc = None

        log.write(f"\n[bold yellow]▶ {prompt}[/bold yellow]")

        try:
            env = {**os.environ}
            self._proc = await asubprocess.create_subprocess_exec(
                self._cc_path,
                "--print",
                prompt,
                stdout=asubprocess.PIPE,
                stderr=asubprocess.STDOUT,
                env=env,
            )
            asyncio.get_event_loop().create_task(self._stream_output(self._proc, log))
        except Exception as exc:
            log.write(f"[red]Błąd uruchamiania CC: {exc}[/red]")

    async def _stream_output(self, proc: asubprocess.Process, log: RichLog) -> None:
        assert proc.stdout is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                log.write(text)
        except Exception as exc:
            log.write(f"[red]Błąd odczytu: {exc}[/red]")
        finally:
            await proc.wait()
            rc = proc.returncode
            if rc == 0:
                log.write("[dim green]✓ Zakończono[/dim green]")
            else:
                log.write(f"[dim red]✗ Kod wyjścia: {rc}[/dim red]")

    def action_clear_log(self) -> None:
        self.query_one("#cc-log", RichLog).clear()

    def action_interrupt(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            log = self.query_one("#cc-log", RichLog)
            log.write("[yellow]Przerwano.[/yellow]")


class TostWithCCApp(App):
    """TOST + panel Claude Code — side by side."""

    TITLE = "TOST + CC"
    SUB_TITLE = "Token Monitor & Claude Code"

    CSS = """
    Screen { layout: vertical; }

    #main-area {
        height: 1fr;
        layout: horizontal;
    }

    #left-panel {
        width: 60%;
        border: solid $accent;
    }

    #left-title {
        height: 1;
        padding: 0 2;
        color: $accent;
        text-style: bold;
    }

    #session-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Odśwież"),
        Binding("ctrl+l", "clear_cc", "Wyczyść CC"),
        Binding("ctrl+c", "interrupt_cc", "Przerwij CC"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            with Vertical(id="left-panel"):
                yield Label(" SESJE  (odświeżanie co 15s — R aby teraz)", id="left-title")
                yield SummaryBar()
                yield DataTable(id="session-table")
            yield CCTerminalPanel()
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
                format_cost(s.cost_usd),
            )
        self.query_one(SummaryBar).update_summary(sessions)

    def action_clear_cc(self) -> None:
        self.query_one(CCTerminalPanel).action_clear_log()

    def action_interrupt_cc(self) -> None:
        self.query_one(CCTerminalPanel).action_interrupt()
