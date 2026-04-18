"""THC Mini — ultra-minimalny widok 3 kropek nacisku na limity.

Pokazuje dokladnie 3 kropki w kolorach zgodnych z panelem NACISK NA LIMITY z THC:

    ●  ●  ●
    │  │  └── BURN-RATE tokenow (taryfa — ratio/z-score vs 7-dniowy baseline)
    │  └───── PING 1h (avg TTFB z tost_ping.db)
    └──────── GODZINA (tier serwerowy wg thc_tiers.toml)

Paleta taka sama jak w ThcTaryfaPanel:
    GREEN / ZIELONA      → #39FF14
    YELLOW / ZOLTA       → #FFD700
    ORANGE / POMARANCZOWA→ #FF8800
    RED / CZERWONA       → #FF3030
    BRAK danych          → #004400 (ciemny szary)

Odswiezanie co 5 s (spojne z THC). Read-only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from tost.ping import PingState, DEFAULT_PING_DB
from tost.taryfa import (
    TARYFA_COLORS, TaryfaState, compute_tariff,
    reload_thresholds, scan_new_records,
)
from tost.thc import MATRIX_BLACK, MATRIX_DARK, _ping_pressure_level
from tost.thc_tiers import TIER_COLORS, get_tier, reload_schedule


REFRESH_INTERVAL = 5.0


class ThcMiniApp(App):
    """Mini-okno: 3 kropki, nic wiecej."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("ctrl+r", "reload_toml", "Reload TOML"),
    ]

    CSS = f"""
    Screen {{
        background: {MATRIX_BLACK};
        align: center middle;
    }}
    #dots {{
        width: auto;
        height: 1;
        content-align: center middle;
        text-style: bold;
    }}
    """

    def __init__(self) -> None:
        super().__init__()
        self._taryfa_state: TaryfaState | None = None

    def compose(self) -> ComposeResult:
        yield Static("●  ●  ●", id="dots")

    def on_mount(self) -> None:
        try:
            self._taryfa_state = TaryfaState()
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"Taryfa state init failed: {e}")
        self.action_refresh_now()
        self.set_interval(REFRESH_INTERVAL, self.action_refresh_now)

    def on_unmount(self) -> None:
        if self._taryfa_state is not None:
            try:
                self._taryfa_state.close()
            except Exception:  # noqa: BLE001
                pass

    def _ping_color(self) -> str:
        if not DEFAULT_PING_DB.exists():
            return MATRIX_DARK
        state: PingState | None = None
        try:
            state = PingState(DEFAULT_PING_DB)
            rolling = state.get_rolling_avg_minutes(60, "api")
            avg = float(rolling.get("avg_ttfb") or 0.0)
            _, color = _ping_pressure_level(avg)
            return color
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"Ping rolling avg failed: {e}")
            return MATRIX_DARK
        finally:
            if state is not None:
                try:
                    state.close()
                except Exception:  # noqa: BLE001
                    pass

    def _burn_color(self) -> str:
        if self._taryfa_state is None:
            return MATRIX_DARK
        try:
            scan_new_records(self._taryfa_state)
            reading = compute_tariff(self._taryfa_state)
            return TARYFA_COLORS[reading.taryfa]
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"Taryfa compute failed: {e}")
            return MATRIX_DARK

    def action_refresh_now(self) -> None:
        now = datetime.now(timezone.utc)
        tier_color = TIER_COLORS[get_tier(now)]
        ping_color = self._ping_color()
        burn_color = self._burn_color()
        self.query_one("#dots", Static).update(
            f"[{tier_color}]●[/]  [{ping_color}]●[/]  [{burn_color}]●[/]"
        )

    def action_reload_toml(self) -> None:
        try:
            reload_schedule()
            reload_thresholds()
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"Reload TOML failed: {e}")
        self.action_refresh_now()


def main() -> None:
    ThcMiniApp().run()


if __name__ == "__main__":
    main()
