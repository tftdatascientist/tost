"""Trainer TUI — interactive context engineering course powered by Haiku."""

from __future__ import annotations

import threading

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Header, Footer, Static, DataTable, Label, Input, Button,
)

from tost.trainer import CURRICULUM, TrainerState, call_haiku


TRAINER_CSS = """
    TrainerScreen {
        layout: horizontal;
    }
    #trainer-sidebar {
        width: 32;
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    #module-table {
        height: 1fr;
    }
    #trainer-main {
        width: 1fr;
        height: 1fr;
    }
    #lesson-header {
        height: 3;
        border: solid $accent;
        padding: 0 1;
        text-style: bold;
    }
    #chat-scroll {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    #chat-log {
        height: auto;
    }
    .msg-assistant {
        color: $success;
        margin: 0 0 1 0;
    }
    .msg-user {
        color: $warning;
        margin: 0 0 1 0;
    }
    .msg-system {
        color: $accent;
        text-style: italic;
        margin: 0 0 1 0;
    }
    #input-row {
        height: 3;
        dock: bottom;
    }
    #chat-input {
        width: 1fr;
    }
    #btn-send {
        width: 12;
    }
    #btn-next {
        width: 12;
    }
    .panel-title {
        text-style: bold;
        color: $text;
    }
    #loading-indicator {
        color: $accent;
        text-style: italic;
    }
"""


class TrainerScreen(Screen):
    """Interactive trainer screen — pushable onto any Textual App."""

    CSS = TRAINER_CSS

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("s", "open_sim", "Simulator"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state = TrainerState()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="trainer-sidebar"):
                yield Label(" MODULES ", classes="panel-title")
                yield DataTable(id="module-table")
            with Vertical(id="trainer-main"):
                yield Label("", id="lesson-header")
                with VerticalScroll(id="chat-scroll"):
                    yield Vertical(id="chat-log")
                yield Label("", id="loading-indicator")
                with Horizontal(id="input-row"):
                    yield Input(
                        placeholder="Type your answer (or 'next' to skip)...",
                        id="chat-input",
                    )
                    yield Button("Send", id="btn-send", variant="primary")
                    yield Button("Next", id="btn-next", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        # Build module table
        table = self.query_one("#module-table", DataTable)
        table.add_columns("", "Module", "Lessons")
        table.cursor_type = "row"
        self._refresh_modules()
        self._update_lesson_header()
        # Auto-start first lesson
        self._call_haiku_async()

    def _refresh_modules(self) -> None:
        table = self.query_one("#module-table", DataTable)
        table.clear()
        for i, mod in enumerate(CURRICULUM):
            marker = ">>>" if i == self._state.current_module else "   "
            if mod.id in self._state.completed_modules:
                marker = " * "
            table.add_row(
                marker,
                f"{mod.icon} {mod.name}",
                str(len(mod.lessons)),
                key=str(i),
            )

    def _update_lesson_header(self) -> None:
        mod = self._state.module
        les = self._state.lesson
        idx = self._state.current_lesson + 1
        total = len(mod.lessons)
        self.query_one("#lesson-header", Label).update(
            f" {mod.icon} {mod.name}  —  Lesson {idx}/{total}: {les.title} "
        )

    def _append_chat(self, role: str, text: str) -> None:
        log = self.query_one("#chat-log", Vertical)
        css_class = f"msg-{role}"
        prefix = {"assistant": "Haiku", "user": "You", "system": ">>"}[role]
        label = Label(f"[{prefix}] {text}", classes=css_class)
        log.mount(label)
        # Scroll to bottom
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def _set_loading(self, loading: bool) -> None:
        indicator = self.query_one("#loading-indicator", Label)
        indicator.update("  Haiku is thinking..." if loading else "")
        self.query_one("#btn-send", Button).disabled = loading
        self.query_one("#chat-input", Input).disabled = loading

    def _call_haiku_async(self, user_input: str | None = None) -> None:
        """Call Haiku in a background thread to keep TUI responsive."""
        self._set_loading(True)

        def _worker() -> None:
            try:
                response = call_haiku(self._state, user_input)
                self.app.call_from_thread(self._on_haiku_response, response)
            except Exception as e:
                self.app.call_from_thread(
                    self._on_haiku_error, str(e)
                )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_haiku_response(self, text: str) -> None:
        self._set_loading(False)
        self._append_chat("assistant", text)

    def _on_haiku_error(self, error: str) -> None:
        self._set_loading(False)
        self._append_chat("system", f"Error: {error}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-send":
            self._send_message()
        elif event.button.id == "btn-next":
            self._next_lesson()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            self._send_message()

    def _send_message(self) -> None:
        inp = self.query_one("#chat-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""
        self._append_chat("user", text)
        self._call_haiku_async(text)

    def _next_lesson(self) -> None:
        if self._state.advance():
            # Clear chat log
            log = self.query_one("#chat-log", Vertical)
            log.remove_children()
            self._refresh_modules()
            self._update_lesson_header()
            self._append_chat("system", f"Starting: {self._state.lesson.title}")
            self._call_haiku_async()
        else:
            self._append_chat("system", "Congratulations! You completed the entire curriculum.")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        if table.id != "module-table":
            return
        index = int(str(event.row_key.value))
        self._state.jump_to_module(index)
        # Clear chat and start
        log = self.query_one("#chat-log", Vertical)
        log.remove_children()
        self._refresh_modules()
        self._update_lesson_header()
        self._append_chat("system", f"Jumping to: {self._state.module.name}")
        self._call_haiku_async()

    def action_open_sim(self) -> None:
        """Open simulator from within trainer."""
        from tost.sim_dashboard import SimScreen
        self.app.push_screen(SimScreen())

    def action_go_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()


class TrainerApp(App):
    """Standalone TOST Trainer app (used by `tost train` CLI command)."""

    TITLE = "TOST"
    SUB_TITLE = "Context Engineering Trainer"

    CSS = TRAINER_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.push_screen(TrainerScreen())
