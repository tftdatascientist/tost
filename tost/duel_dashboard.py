"""Interactive duel TUI — two CC profiles face off on token cost."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, DataTable, Label, Input, Button

from tost.cost import format_cost
from tost.duel import (
    Profile, DuelResult, get_preset_profiles, run_duel,
)
from tost.simulator import SimConfig


# ── Profile selector ────────────────────────────────────────────────────────

class ProfileSelector(Static):
    """Select a profile from presets."""

    def __init__(self, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._side = side  # "A" or "B"
        self._profiles = get_preset_profiles()
        self._selected: int = 0 if side == "A" else 1

    def compose(self) -> ComposeResult:
        yield Label(f" PROFILE {self._side} ", classes="panel-title")
        yield DataTable(id=f"profile-table-{self._side}")

    def on_mount(self) -> None:
        table = self.query_one(f"#profile-table-{self._side}", DataTable)
        table.add_columns("", "Name", "Model", "Sess", "Msg", "Total", "Description")
        table.cursor_type = "row"
        self._populate()

    def _populate(self) -> None:
        table = self.query_one(f"#profile-table-{self._side}", DataTable)
        table.clear()
        for i, p in enumerate(self._profiles):
            marker = " ▶ " if i == self._selected else "   "
            table.add_row(
                marker,
                p.name,
                p.model.replace("claude-", ""),
                f"{p.session_tokens:,}",
                f"{p.per_message_tokens:,}",
                f"{p.total_config_tokens:,}",
                p.description[:40],
                key=str(i),
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        if table.id != f"profile-table-{self._side}":
            return
        self._selected = int(str(event.row_key.value))
        self._populate()

    def get_selected_profile(self) -> Profile:
        return self._profiles[self._selected]


# ── Duel params ─────────────────────────────────────────────────────────────

class DuelParams(Static):
    """Shared simulation parameters for the duel."""

    def compose(self) -> ComposeResult:
        yield Label(" DUEL PARAMETERS ", classes="panel-title")
        with Horizontal(classes="param-row"):
            yield Label("Messages:      ", classes="param-label")
            yield Input(value="30", id="duel-messages", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("User tok/msg:  ", classes="param-label")
            yield Input(value="200", id="duel-user-tok", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Asst tok/msg:  ", classes="param-label")
            yield Input(value="800", id="duel-asst-tok", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Tools/msg:     ", classes="param-label")
            yield Input(value="1.5", id="duel-tools", type="number", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Cache hit %:   ", classes="param-label")
            yield Input(value="70", id="duel-cache", type="integer", classes="param-input")
        with Horizontal(classes="param-row"):
            yield Label("Context keep %:", classes="param-label")
            yield Input(value="85", id="duel-context", type="integer", classes="param-input")
        yield Button("⚔  FIGHT!", id="btn-duel", variant="warning")

    def get_config(self) -> SimConfig:
        return SimConfig(
            num_messages=int(self.query_one("#duel-messages", Input).value or 30),
            avg_user_tokens=int(self.query_one("#duel-user-tok", Input).value or 200),
            avg_assistant_tokens=int(self.query_one("#duel-asst-tok", Input).value or 800),
            tools_per_message=float(self.query_one("#duel-tools", Input).value or 1.5),
            cache_hit_rate=int(self.query_one("#duel-cache", Input).value or 70) / 100,
            context_growth_rate=int(self.query_one("#duel-context", Input).value or 85) / 100,
        )


# ── Results panel ───────────────────────────────────────────────────────────

class DuelResultPanel(Static):
    """Shows duel results."""

    def compose(self) -> ComposeResult:
        yield Label(" DUEL RESULTS ", classes="panel-title")
        yield Label("Select two profiles and hit FIGHT!", id="duel-result-text")


class DuelChartPanel(Static):
    """ASCII chart comparing both profiles."""

    def compose(self) -> ComposeResult:
        yield Label(" COST COMPARISON CHART ", classes="panel-title")
        yield Label("Waiting for duel...", id="duel-chart-text")


# ── Duel screen ─────────────────────────────────────────────────────────────

DUEL_CSS = """
    DuelScreen, Screen {
        layout: vertical;
        overflow-y: auto;
    }
    #profiles-row {
        height: auto;
        max-height: 16;
    }
    ProfileSelector {
        width: 1fr;
        height: auto;
        border: solid $accent;
        padding: 0 1;
    }
    #profile-table-A, #profile-table-B {
        height: auto;
        max-height: 12;
    }
    #params-row {
        height: auto;
        max-height: 22;
    }
    DuelParams {
        width: 40;
        height: auto;
        border: solid $warning;
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
    #btn-duel {
        margin: 1 0;
        width: 100%;
    }
    DuelResultPanel {
        height: auto;
        min-height: 20;
        border: solid $success;
        padding: 0 1;
    }
    DuelChartPanel {
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


class DuelScreen(Screen):
    """Duel screen — two profiles compete on token cost."""

    CSS = DUEL_CSS

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("enter", "run_duel", "Fight!"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            with Horizontal(id="profiles-row"):
                yield ProfileSelector("A")
                yield ProfileSelector("B")
            with Horizontal(id="params-row"):
                yield DuelParams()
                yield DuelResultPanel()
            yield DuelChartPanel()
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-duel":
            self.action_run_duel()

    def action_go_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()

    def action_run_duel(self) -> None:
        selectors = self.query(ProfileSelector)
        sel_a = sel_b = None
        for s in selectors:
            if s._side == "A":
                sel_a = s
            else:
                sel_b = s

        if not sel_a or not sel_b:
            return

        profile_a = sel_a.get_selected_profile()
        profile_b = sel_b.get_selected_profile()
        cfg = self.query_one(DuelParams).get_config()

        result = run_duel(profile_a, profile_b, cfg)

        self._render_results(result)
        self._render_chart(result)

    def _render_results(self, result: DuelResult) -> None:
        pa = result.profile_a
        pb = result.profile_b
        lines = []

        # Header
        lines.append(f"  {'':>25} {'[A] ' + pa.name:>22}  {'[B] ' + pb.name:>22}")
        lines.append(f"  {'─'*72}")

        # Config comparison
        lines.append(f"  {'Model':<25} {pa.model:>22}  {pb.model:>22}")
        lines.append(f"  {'Session start tokens':<25} {pa.session_tokens:>21,}  {pb.session_tokens:>21,}")
        lines.append(f"  {'Per-message tokens':<25} {pa.per_message_tokens:>21,}  {pb.per_message_tokens:>21,}")
        lines.append(f"  {'Total config tokens':<25} {pa.total_config_tokens:>21,}  {pb.total_config_tokens:>21,}")
        lines.append(f"  {'─'*72}")

        # Component diff
        lines.append("")
        lines.append("  COMPONENTS:")
        all_comps_a = {(c.name, c.category) for c in pa.components}
        all_comps_b = {(c.name, c.category) for c in pb.components}
        all_keys = sorted(all_comps_a | all_comps_b)

        comp_map_a = {(c.name, c.category): c for c in pa.components}
        comp_map_b = {(c.name, c.category): c for c in pb.components}

        for name, cat in all_keys:
            in_a = (name, cat) in all_comps_a
            in_b = (name, cat) in all_comps_b
            tok_a = comp_map_a[(name, cat)].tokens if in_a else 0
            tok_b = comp_map_b[(name, cat)].tokens if in_b else 0
            marker_a = f"{tok_a:>6,}" if in_a else "    - "
            marker_b = f"{tok_b:>6,}" if in_b else "    - "
            cat_short = "ses" if cat == "session_start" else "msg"
            diff_marker = " " if in_a == in_b else "*"
            lines.append(f"  {diff_marker} {name:<30} [{cat_short}]  {marker_a}  {marker_b}")

        lines.append(f"  {'─'*72}")

        # Cost results
        lines.append("")
        lines.append(f"  TOTAL COST ({result.config.num_messages} msgs):")
        lines.append(f"  {'[A] ' + pa.name + ':':<25} {format_cost(result.total_cost_a):>12}")
        lines.append(f"  {'[B] ' + pb.name + ':':<25} {format_cost(result.total_cost_b):>12}")
        lines.append(f"  {'─'*40}")

        # Winner
        if result.savings > 0.0001:
            lines.append(
                f"  WINNER: {result.winner}  "
                f"(saves {format_cost(result.savings)}, -{result.savings_pct:.1f}%)"
            )
        else:
            lines.append("  TIE — both profiles cost the same")

        self.query_one("#duel-result-text", Label).update("\n".join(lines))

    def _render_chart(self, result: DuelResult) -> None:
        msgs = result.messages
        if not msgs:
            return

        max_cost = max(msgs[-1].cumulative_a, msgs[-1].cumulative_b)
        if max_cost <= 0:
            self.query_one("#duel-chart-text", Label).update("Cost too small to chart")
            return

        chart_width = 60
        chart_height = 10
        lines = []

        pa = result.profile_a
        pb = result.profile_b

        lines.append(f"  [A] {pa.name}: {format_cost(result.total_cost_a)}  vs  [B] {pb.name}: {format_cost(result.total_cost_b)}")
        lines.append(f"  Savings: {format_cost(result.savings)} ({result.savings_pct:.1f}%)")
        lines.append("")

        # Sample messages
        step = max(1, len(msgs) // chart_width)
        sampled = msgs[::step][:chart_width]

        # Scale labels
        for row in range(chart_height, -1, -1):
            threshold = max_cost * row / chart_height
            label = f"  {format_cost(threshold):>9} │"
            bar = ""
            for m in sampled:
                a_above = m.cumulative_a >= threshold
                b_above = m.cumulative_b >= threshold
                if a_above and b_above:
                    bar += "█"  # both
                elif a_above:
                    bar += "▓"  # only A
                elif b_above:
                    bar += "░"  # only B
                else:
                    bar += " "
            lines.append(f"{label}{bar}")

        # X axis
        lines.append(f"  {'':>9} └{'─' * len(sampled)}")
        lines.append(f"  {'':>9}  1{'':>{len(sampled)-3}}{len(msgs)}")
        lines.append(f"  {'':>12}Messages →")

        lines.append("")
        lines.append(f"  █ = Both profiles  ▓ = Only [A] {pa.name}  ░ = Only [B] {pb.name}")

        # Per-message table
        lines.append("")
        lines.append(f"  {'#':>3}  {'Context':>8}  {'Cost A':>10}  {'Cost B':>10}  {'Delta':>10}  {'Cum A':>10}  {'Cum B':>10}")
        lines.append(f"  {'─'*76}")

        show = []
        if len(msgs) <= 12:
            show = msgs
        else:
            show = msgs[:5] + [None] + msgs[-5:]

        for m in show:
            if m is None:
                lines.append(f"  {'...':>3}")
                continue
            delta_marker = "A+" if m.cost_delta > 0 else "B+"
            lines.append(
                f"  {m.msg_number:>3}  "
                f"{m.context_tokens:>7,}  "
                f"{format_cost(m.cost_a):>10}  "
                f"{format_cost(m.cost_b):>10}  "
                f"{delta_marker}{format_cost(abs(m.cost_delta)):>7}  "
                f"{format_cost(m.cumulative_a):>10}  "
                f"{format_cost(m.cumulative_b):>10}"
            )

        self.query_one("#duel-chart-text", Label).update("\n".join(lines))


class DuelApp(App):
    """Standalone TOST Duel app (used by `tost duel` CLI command)."""

    TITLE = "TOST"
    SUB_TITLE = "Duel Mode — Profile vs Profile"

    CSS = DUEL_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.push_screen(DuelScreen())
