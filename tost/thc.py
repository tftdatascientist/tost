"""THC — Traffic Hours Console (Matrix TUI dla monitoringu pingu Anthropic).

Layout:
    ┌ clock ─┬ ping ─┬ tier stats ─┐
    │ zegar  │ now   │ avg per tier│
    │ tier   │ 1h    │ 7 dni       │
    │ NEXT → │ today │             │
    ├────────┴───────┴─────────────┤
    │ NACISK  godz · ping · burn   │
    │ 24h bar chart tokenow burnu  │  ← srodkowy panel: pelna doba UTC
    ├──────────────────────────────┤
    │ 24H PROFIL (bar chart TTFB)  │  ← srodkowy panel: pelna doba UTC
    ├──────────────────────────────┤
    │ RECENT PINGS (DataTable 1fr) │
    └──────────────────────────────┘

Srodkowe panele rysuja wielowierszowy pionowy bar chart pokrywajacy pelna
dobe (24 godziny UTC). Kazda godzina zajmuje 2 kolumny terminala, skala
godzin, oś X i pasek tierow sa wyrownane 1:1 ze slupkami.

Read-only: dane bierze z tost_ping.db zapisywanej przez `tost ping-collect`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from itertools import zip_longest

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, DataTable, Static, Digits

try:
    from zoneinfo import ZoneInfo
    CET_TZ = ZoneInfo("Europe/Warsaw")
    US_EAST_TZ = ZoneInfo("America/New_York")
    US_WEST_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # noqa: BLE001 — fallback gdy brak tzdata
    CET_TZ = timezone(timedelta(hours=1), "CET")
    US_EAST_TZ = timezone(timedelta(hours=-5), "EST")
    US_WEST_TZ = timezone(timedelta(hours=-8), "PST")

from tost.ping import PingState, DEFAULT_PING_DB
from tost.taryfa import (
    TARYFA_COLORS, TARYFA_LABELS, TaryfaReading, TaryfaState,
    compute_tariff, reload_thresholds, scan_new_records,
)
from tost.sound import is_enabled as sonar_is_enabled, toggle_enabled as sonar_toggle
from tost.thc_tiers import (
    Tier, TIER_COLORS, get_tier, next_tier_change,
    next_red_start, red_window_end, reload_schedule,
    schedule_for_hour_range,
)


REFRESH_INTERVAL = 5.0  # sekundy — zegar odświeża się tak samo jak reszta

# ── Matrix palette (zgodna z projektem MTX) ────────────────────────────────
MATRIX_BLACK      = "#000000"
MATRIX_VOID       = "#001100"
MATRIX_ABYSS      = "#002200"
MATRIX_DEEP       = "#003300"
MATRIX_SHADOW     = "#004400"
MATRIX_DARK       = "#005500"
MATRIX_MID_DARK   = "#006600"
MATRIX_MID        = "#008800"
MATRIX_MID_LIGHT  = "#00AA00"
MATRIX_LIGHT      = "#00CC00"
MATRIX_BRIGHT     = "#00EE00"
MATRIX_VIVID      = "#00FF00"
MATRIX_NEON       = "#39FF14"

BLOCKS = "▁▂▃▄▅▆▇█"  # 8 poziomów do wykresu barowego


def _fmt_countdown(td: timedelta) -> str:
    total = max(0, int(td.total_seconds()))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def _bar_char(v: float, max_v: float) -> str:
    if max_v <= 0 or v <= 0:
        return "·"
    idx = min(len(BLOCKS) - 1, int(round((len(BLOCKS) - 1) * v / max_v)))
    return BLOCKS[idx]


# ── Wielowierszowy wykres 24h (wspolny helper dla srodkowych paneli) ───────
#
# Każda godzina doby = 2 kolumny terminala (słupek + separator spacji).
# 24 h × 2 kol. = 48 widocznych znaków na wiersz — pasuje do szerokości paneli
# i pozwala na dokładne wyrównanie słupków, skali godzin i kropek tierów.


HOUR_COL_WIDTH = 2  # liczba kolumn terminala na jedną godzinę (słupek + separator)
CHART_W = HOUR_COL_WIDTH * 24  # widoczna szerokość 24h wykresu w znakach
SIDE_SEP = f"  [{'#004400'}]│[/]  "  # separator miedzy dwoma wykresami (visible = 5)
SIDE_SEP_VISIBLE = 5

_MARKUP_RE = re.compile(r"\[/?[^\]]*\]")


def _visible_len(s: str) -> int:
    """Długość wyświetlana w komórkach terminala — pomija Rich markup."""
    return len(_MARKUP_RE.sub("", s))


def _pad_visible(s: str, width: int) -> str:
    diff = width - _visible_len(s)
    return s + " " * max(0, diff)


def _combine_columns(columns: list[tuple[list[str], int]]) -> list[str]:
    """Składa N bloków (lines, visible_width) obok siebie z separatorem `SIDE_SEP`.

    Krótsze linie dopychane spacjami do zadeklarowanej szerokości bloku.
    Bloki o nierównej liczbie wierszy są dopychane pustymi liniami na dole.
    """
    if not columns:
        return []
    max_rows = max(len(lines) for lines, _ in columns)
    out: list[str] = []
    for i in range(max_rows):
        segs: list[str] = []
        for lines, w in columns:
            s = lines[i] if i < len(lines) else ""
            segs.append(_pad_visible(s, w))
        out.append(SIDE_SEP.join(segs))
    return out


def _combine_lines(left: list[str], right: list[str], width: int = CHART_W) -> list[str]:
    """Backward-compat: 2 bloki o tej samej szerokości."""
    return _combine_columns([(left, width), (right, width)])


def _multirow_bars(
    values: list[float],
    max_v: float,
    rows: int,
    colors: list[str],
    cols_per_hour: int = HOUR_COL_WIDTH,
    hollow: set[int] | None = None,
) -> list[str]:
    """Multi-row pionowy bar chart — pełna doba (24 slupki × `rows` wierszy).

    Każdy wiersz pokrywa `max_v / rows` zakresu wartości; blok fine-grained
    (▁..█) domalowuje cząstkę powyżej progu wiersza. Puste komórki to spacje,
    żeby nie rozpraszać wzroku. Godziny z `hollow` rysowane są jako ramka
    (·) — do oznaczenia „brak pomiaru" bez zaburzania skali.

    `cols_per_hour` steruje szerokością pojedynczej godziny — słupek zajmuje
    `cols_per_hour - 1` znaków, ostatnia kolumna to separator (spacja).
    """
    n = len(values)
    if rows <= 0:
        return []
    bar_width = max(1, cols_per_hour - 1)
    gap_width = cols_per_hour - bar_width  # zwykle 1
    gap = " " * gap_width
    empty_cell = " " * cols_per_hour
    if max_v <= 0:
        return [empty_cell * n for _ in range(rows)]
    step = max_v / rows
    hollow = hollow or set()
    # Kropka hollow wycentrowana w szerokości słupka
    dot_pad_left = (bar_width - 1) // 2
    dot_pad_right = bar_width - 1 - dot_pad_left
    hollow_cell = (
        " " * dot_pad_left
        + f"[{MATRIX_DARK}]·[/]"
        + " " * dot_pad_right
        + gap
    )
    lines: list[str] = []
    for r in range(rows):
        row_floor = (rows - 1 - r) * step
        segs: list[str] = []
        for i, v in enumerate(values):
            if i in hollow and v <= 0:
                segs.append(hollow_cell)
                continue
            delta = v - row_floor
            if delta <= 0:
                segs.append(empty_cell)
                continue
            if delta >= step:
                ch = "█" * bar_width
            else:
                idx = min(
                    len(BLOCKS) - 1,
                    max(0, int(round((len(BLOCKS) - 1) * delta / step))),
                )
                ch = BLOCKS[idx] * bar_width
            segs.append(f"[{colors[i]}]{ch}[/]{gap}")
        lines.append("".join(segs))
    return lines


def _hour_scale(
    mod: int = 3,
    highlight: int | None = None,
    cols_per_hour: int = HOUR_COL_WIDTH,
) -> str:
    """Oś godzin UTC (cols_per_hour/godz.) — etykiety co `mod` godzin, wycentrowane."""
    parts: list[str] = []
    for h in range(24):
        if h % mod == 0:
            label = f"{h:02d}"
            pad_total = max(0, cols_per_hour - len(label))
            pad_left = pad_total // 2
            pad_right = pad_total - pad_left
            padded = " " * pad_left + label + " " * pad_right
            parts.append(
                f"[bold {MATRIX_NEON}]{padded}[/]" if h == highlight
                else f"[{MATRIX_MID}]{padded}[/]"
            )
        else:
            parts.append(" " * cols_per_hour)
    return "".join(parts)


def _tier_dot_row(sched: list[Tier], cols_per_hour: int = HOUR_COL_WIDTH) -> str:
    """Pasek kolorowych kropek tierów — kropka wycentrowana w slocie godziny."""
    pad_total = max(0, cols_per_hour - 1)
    pad_left = pad_total // 2
    pad_right = pad_total - pad_left
    left = " " * pad_left
    right = " " * pad_right
    return "".join(
        f"{left}[{TIER_COLORS[sched[h]]}]●[/]{right}" for h in range(24)
    )


def _render_chart(
    values: list[float],
    max_v: float,
    rows: int,
    colors: list[str],
    sched: list[Tier],
    hour_highlight: int,
    *,
    title: str,
    summary_label: str,
    summary_prefix: str = "avg",
    hollow: set[int] | None = None,
    show_tier_dots: bool = True,
) -> list[str]:
    """Renderuje kompletny jeden 24h chart (header + bars + osie).

    Zwraca listę linii gotowych do `join("\\n")`. Wszystkie wiersze (poza
    headerem) mają wizualną szerokość `CHART_W` — łatwo składa się obok siebie.
    """
    header = (
        f"[bold {MATRIX_NEON}]{title}[/]  "
        f"[{MATRIX_DARK}]{summary_prefix}[/] [bold {MATRIX_MID_LIGHT}]{summary_label}[/] "
        f"[{MATRIX_DARK}]┐[/]"
    )
    bars = _multirow_bars(values, max_v, rows, colors, hollow=hollow)
    lines = [header]
    lines.extend(bars)
    lines.append(f"[{MATRIX_MID_DARK}]" + "─" * CHART_W + "[/]")
    lines.append(_hour_scale(mod=3, highlight=hour_highlight))
    if show_tier_dots:
        lines.append(_tier_dot_row(sched))
    return lines


def _render_pings_chart(
    pings: list,  # list[PingResult], oldest -> newest
    bar_rows: int,
    *,
    slots: int = 20,
    title: str = "OSTATNIE 20",
    shared_max: float | None = None,
    summary_label: str | None = None,
    summary_prefix: str = "avg",
) -> tuple[list[str], int]:
    """Renderuje wykres `slots` ostatnich pingów (TTFB). Zwraca (linie, visible_width).

    Zawsze rezerwuje `slots` pozycji; brakujące (mniej pingów w bazie) to
    hollow-kropki po LEWEJ stronie, nowe wchodzą z PRAWEJ — daje wrażenie
    przesuwania się w miarę jak dochodzą kolejne pomiary.

    `shared_max` pozwala wyrównać skalę słupków do innych wykresów obok
    (żeby 300 ms obok nie wyglądało wyżej niż 600 ms gdzie indziej).
    `max_label` nadpisuje etykietę „max" w headerze (pod wspólną skalę).
    """
    width = slots * HOUR_COL_WIDTH
    n = min(len(pings), slots)
    # LEWA strona: puste hollow-sloty (brak pomiarów), PRAWA: realne pingi
    empty = slots - n
    values: list[float] = [0.0] * empty
    colors: list[str] = [MATRIX_DARK] * empty
    hollow: set[int] = set(range(empty))
    last_pings = pings[-n:] if n > 0 else []
    for p in last_pings:
        values.append(float(p.ttfb_ms))
        try:
            dt = datetime.fromisoformat(p.timestamp.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            dt = datetime.now(timezone.utc)
        colors.append(TIER_COLORS[get_tier(dt)])

    local_max = max((v for v in values if v > 0), default=0.0)
    max_v = shared_max if shared_max is not None and shared_max > 0 else local_max

    # Podswietl najnowszy (skrajny prawy) ping jasno-białym — "live edge"
    # (nie uzywamy MATRIX_NEON, bo rowny tier-color GREEN — bylby nieodroznialny)
    LIVE_EDGE = "#FFFFFF"
    if n > 0:
        colors[-1] = LIVE_EDGE

    bars = _multirow_bars(values, max_v, bar_rows, colors, hollow=hollow)

    if summary_label is None:
        real = [v for v in values if v > 0]
        avg = sum(real) / len(real) if real else 0.0
        summary_label = f"{avg:>5.0f} ms" if avg > 0 else "   — ms"
    header = (
        f"[bold {MATRIX_NEON}]{title}[/]  "
        f"[{MATRIX_DARK}]{summary_prefix}[/] [bold {MATRIX_MID_LIGHT}]{summary_label}[/] "
        f"[{MATRIX_DARK}]┐[/]"
    )

    # Skala: „-Nm" (najstarszy realny ping) po lewej, „now" po prawej
    left_label = ""
    if last_pings:
        try:
            oldest_dt = datetime.fromisoformat(last_pings[0].timestamp.replace("Z", "+00:00"))
            mins_ago = max(0, int((datetime.now(timezone.utc) - oldest_dt).total_seconds() / 60))
            left_label = f"-{mins_ago}m"
        except Exception:  # noqa: BLE001
            left_label = ""
    right_label = "now" if last_pings else ""
    gap = width - len(left_label) - len(right_label)
    if gap >= 1:
        scale_plain = left_label + " " * gap + right_label
    else:
        scale_plain = right_label.rjust(width)
    scale = f"[{MATRIX_MID}]{scale_plain}[/]"

    # Tier dots — kropka per slot; najnowszy ping to ◉ (fisheye) na bialo,
    # puste sloty szare · — daje wyrazny wskaznik "live edge"
    dot_parts: list[str] = []
    for i in range(slots):
        if i < empty:
            dot_parts.append(f"[{MATRIX_DARK}]·[/] ")
        elif i == slots - 1 and n > 0:
            dot_parts.append(f"[bold {LIVE_EDGE}]◉[/] ")
        else:
            dot_parts.append(f"[{colors[i]}]●[/] ")
    dots = "".join(dot_parts)

    lines = [header]
    lines.extend(bars)
    lines.append(f"[{MATRIX_MID_DARK}]" + "─" * width + "[/]")
    lines.append(scale)
    lines.append(dots)
    return lines, width


def _baseline_hourly_medians(ts: TaryfaState, today_iso: str) -> dict[int, int]:
    """Mediana tokenów per godzina UTC z ostatnich 7 dni (bez dziś)."""
    result: dict[int, int] = {}
    for h in range(24):
        samples = ts.get_baseline_for_hour(h, 7, today_iso)
        if samples:
            samples.sort()
            result[h] = samples[len(samples) // 2]
    return result


# ── Widgety ────────────────────────────────────────────────────────────────


class ThcClock(Vertical):
    """Duży zegar CET + info o tierze + 2 male zegary USA (East/West)."""

    DEFAULT_CSS = f"""
    ThcClock {{
        height: 100%;
        padding: 1 2;
        border: solid {MATRIX_MID_DARK};
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
    }}
    ThcClock #clock-header {{
        height: 1;
        width: 100%;
        color: {MATRIX_NEON};
        text-style: bold;
    }}
    ThcClock #clock-cet {{
        width: 100%;
        height: 3;
        color: {MATRIX_BRIGHT};
        content-align: center middle;
        text-style: bold;
    }}
    ThcClock #clock-info {{
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }}
    ThcClock #clock-us-row {{
        height: 3;
        width: 100%;
    }}
    ThcClock .us-clock {{
        width: 1fr;
        height: 3;
        border: solid {MATRIX_DEEP};
        padding: 0 1;
        content-align: center middle;
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static("◈ CLOCK  CET", id="clock-header")
        yield Digits("00:00:00", id="clock-cet")
        yield Static("", id="clock-info")
        with Horizontal(id="clock-us-row"):
            yield Static("", id="clock-us-east", classes="us-clock")
            yield Static("", id="clock-us-west", classes="us-clock")

    def refresh_data(self) -> None:
        now = datetime.now(timezone.utc)
        now_cet = now.astimezone(CET_TZ)
        now_east = now.astimezone(US_EAST_TZ)
        now_west = now.astimezone(US_WEST_TZ)
        tier = get_tier(now)
        nxt_tier, nxt_when = next_tier_change(now)
        red_end = red_window_end(now)
        nxt_red = next_red_start(now)
        tier_color = TIER_COLORS[tier]

        self.query_one("#clock-cet", Digits).update(now_cet.strftime("%H:%M:%S"))

        info_lines: list[str] = []
        info_lines.append(
            f"[{MATRIX_MID_LIGHT}]{now_cet.strftime('%Z')}[/] "
            f"[{MATRIX_DARK}]{now_cet.strftime('%a %d %b %Y')}[/]   "
            f"[{MATRIX_MID}]UTC[/] [{MATRIX_BRIGHT}]{now.strftime('%H:%M:%S')}[/]"
        )
        info_lines.append(
            f"[{MATRIX_MID}]TIER  [/][bold {tier_color}]● {tier.value}[/]   "
            f"[{MATRIX_MID}]NEXT  [/][bold {TIER_COLORS[nxt_tier]}]{nxt_tier.value}[/]"
            f" [{MATRIX_MID}]in[/] [{MATRIX_BRIGHT}]{_fmt_countdown(nxt_when - now)}[/]"
        )
        if red_end:
            info_lines.append(
                f"[bold {TIER_COLORS[Tier.RED]}]● RED ACTIVE[/] "
                f"[{MATRIX_MID}]ends in[/] [{MATRIX_BRIGHT}]{_fmt_countdown(red_end - now)}[/]"
            )
        else:
            info_lines.append(
                f"[{MATRIX_MID}]RED   in[/] [{MATRIX_BRIGHT}]{_fmt_countdown(nxt_red - now)}[/] "
                f"[{MATRIX_DARK}]({nxt_red.strftime('%a %H:%M UTC')})[/]"
            )
        self.query_one("#clock-info", Static).update("\n".join(info_lines))

        self.query_one("#clock-us-east", Static).update(
            f"[{MATRIX_MID}]US EAST[/]  [bold {MATRIX_LIGHT}]{now_east.strftime('%H:%M:%S')}[/]\n"
            f"[{MATRIX_DARK}]{now_east.strftime('%Z')} · {now_east.strftime('%a %d %b')}[/]"
        )
        self.query_one("#clock-us-west", Static).update(
            f"[{MATRIX_MID}]US WEST[/]  [bold {MATRIX_LIGHT}]{now_west.strftime('%H:%M:%S')}[/]\n"
            f"[{MATRIX_DARK}]{now_west.strftime('%Z')} · {now_west.strftime('%a %d %b')}[/]"
        )


class ThcPingPanel(Static):
    """Aktualny ping, rolling 1h, today avg (target=api)."""

    DEFAULT_CSS = f"""
    ThcPingPanel {{
        height: 100%;
        padding: 1 2;
        border: solid {MATRIX_MID_DARK};
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
    }}
    """

    def refresh_data(self, state: PingState | None) -> None:
        lines: list[str] = [f"[bold {MATRIX_NEON}]◈ PING  api.anthropic.com[/]", ""]
        if state is None:
            lines.append(f"[{MATRIX_DARK}]brak bazy tost_ping.db —[/]")
            lines.append(f"[{MATRIX_DARK}]uruchom `tost ping-collect`[/]")
            self.update("\n".join(lines))
            return

        latest = state.get_latest(1, target="api")
        rolling = state.get_rolling_avg_minutes(60, "api")
        daily = state.get_daily_avg("api")

        if latest:
            last = latest[0]
            tier_at = get_tier(datetime.fromisoformat(last.timestamp.replace("Z", "+00:00")))
            lines.append(
                f"[{MATRIX_MID}]NOW  [/] "
                f"TTFB [bold {MATRIX_BRIGHT}]{last.ttfb_ms:>5.0f}[/] "
                f"[{MATRIX_DARK}]ms[/]  "
                f"Total [{MATRIX_LIGHT}]{last.total_ms:>5.0f}[/] "
                f"[bold {TIER_COLORS[tier_at]}]●[/]"
            )
            lines.append(f"[{MATRIX_DARK}]{last.timestamp[:19]} UTC[/]")
        else:
            lines.append(f"[{MATRIX_DARK}]brak pomiarów[/]")
            lines.append("")
        lines.append("")
        lines.append(
            f"[{MATRIX_MID}]1h   [/] "
            f"TTFB [bold]{rolling['avg_ttfb']:>5.0f}[/] "
            f"[{MATRIX_DARK}]ms[/]  "
            f"Total {rolling['avg_total']:>5.0f} "
            f"[{MATRIX_DARK}]({rolling['sample_count']} prób)[/]"
        )
        lines.append(
            f"[{MATRIX_MID}]24h  [/] "
            f"TTFB [bold]{daily['avg_ttfb']:>5.0f}[/] "
            f"[{MATRIX_DARK}]ms[/]  "
            f"Total {daily['avg_total']:>5.0f} "
            f"[{MATRIX_DARK}]({daily['sample_count']} prób, {daily['error_count']} err)[/]"
        )
        self.update("\n".join(lines))


class ThcTierStats(Static):
    """Średnie TTFB per tier z ostatnich 7 dni — pokazuje korelację tier↔ping."""

    DEFAULT_CSS = f"""
    ThcTierStats {{
        height: 100%;
        padding: 1 2;
        border: solid {MATRIX_MID_DARK};
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
    }}
    """

    def refresh_data(self, state: PingState | None) -> None:
        lines: list[str] = [f"[bold {MATRIX_NEON}]◈ TIER STATS  7d[/]", ""]
        if state is None:
            lines.append(f"[{MATRIX_DARK}](brak danych)[/]")
            self.update("\n".join(lines))
            return

        hourly = state.get_hourly_summary(7, "api")
        # Grupuj średnie per tier (ważone liczbą próbek)
        tier_agg: dict[Tier, dict[str, float]] = {
            t: {"ttfb_sum": 0.0, "total_sum": 0.0, "samples": 0.0, "errors": 0.0}
            for t in Tier
        }
        sched = schedule_for_hour_range(weekend=False)
        for row in hourly:
            h = row["hour"]
            t = sched[h]
            samples = row["sample_count"] or 0
            tier_agg[t]["ttfb_sum"]  += (row["avg_ttfb"] or 0) * samples
            tier_agg[t]["total_sum"] += (row["avg_total"] or 0) * samples
            tier_agg[t]["samples"]   += samples
            tier_agg[t]["errors"]    += row["error_count"] or 0

        for t in (Tier.GREEN, Tier.YELLOW, Tier.ORANGE, Tier.RED):
            a = tier_agg[t]
            if a["samples"] > 0:
                avg_ttfb = a["ttfb_sum"] / a["samples"]
                lines.append(
                    f"[bold {TIER_COLORS[t]}]●[/] "
                    f"[{MATRIX_MID_LIGHT}]{t.value:<6}[/] "
                    f"TTFB [bold]{avg_ttfb:>5.0f}[/] "
                    f"[{MATRIX_DARK}]ms  ({int(a['samples']):>4} prób)[/]"
                )
            else:
                lines.append(
                    f"[bold {TIER_COLORS[t]}]●[/] "
                    f"[{MATRIX_DARK}]{t.value:<6} — brak danych[/]"
                )
        self.update("\n".join(lines))


def _ping_pressure_level(avg_ttfb_ms: float) -> tuple[str, str]:
    """Klasyfikuje rolling 1h TTFB na tier-like poziom nacisku serwera."""
    if avg_ttfb_ms <= 0:
        return "BRAK", MATRIX_DARK
    if avg_ttfb_ms < 500:
        return "GREEN", TIER_COLORS[Tier.GREEN]
    if avg_ttfb_ms < 1000:
        return "YELLOW", TIER_COLORS[Tier.YELLOW]
    if avg_ttfb_ms < 2000:
        return "ORANGE", TIER_COLORS[Tier.ORANGE]
    return "RED", TIER_COLORS[Tier.RED]


class ThcTaryfaPanel(Vertical):
    """Okno nacisku na limity — 3 kolorowe wskaźniki obok siebie.

    Warstwy:
      1. GODZINA     — tier serwerowy wg pory doby (thc_tiers.toml)
      2. PING 1h     — średni TTFB z ostatniej godziny (latency serwera)
      3. BURN        — taryfa burn-rate tokenów (ratio/z-score vs baseline 7d)

    Pod wskaźnikami: szczegóły taryfy + sparkline 24h.
    """

    # Wysokosc pionowego bar chartu (liczba wierszy slupkow dla tokenow/godz)
    SPARK_ROWS = 5

    DEFAULT_CSS = f"""
    ThcTaryfaPanel {{
        height: 16;
        padding: 0 1;
        border: solid {MATRIX_MID_DARK};
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
    }}
    ThcTaryfaPanel #taryfa-header {{
        height: 1;
        width: 100%;
        color: {MATRIX_NEON};
        text-style: bold;
    }}
    ThcTaryfaPanel #taryfa-indicators {{
        height: 5;
        width: 100%;
    }}
    ThcTaryfaPanel .ind-box {{
        width: 1fr;
        height: 5;
        border: solid {MATRIX_DEEP};
        padding: 0 1;
        content-align: center middle;
    }}
    ThcTaryfaPanel #taryfa-detail {{
        height: 1;
        width: 100%;
    }}
    ThcTaryfaPanel #taryfa-spark {{
        height: 8;
        width: 100%;
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static("◈ NACISK NA LIMITY  godzina · ping 1h · burn-rate", id="taryfa-header")
        with Horizontal(id="taryfa-indicators"):
            yield Static("", id="ind-tier", classes="ind-box")
            yield Static("", id="ind-ping", classes="ind-box")
            yield Static("", id="ind-burn", classes="ind-box")
        yield Static("", id="taryfa-detail")
        yield Static("", id="taryfa-spark")

    def refresh_data(
        self,
        reading: TaryfaReading | None,
        hourly_today: dict[int, int] | None = None,
        baseline_hourly: dict[int, int] | None = None,
        ping_avg_ttfb: float = 0.0,
        sonar_on: bool = True,
    ) -> None:
        # ── 1. GODZINA (tier serwerowy) ────────────────────────────────────
        now = datetime.now(timezone.utc)
        tier = get_tier(now)
        tier_color = TIER_COLORS[tier]
        self.query_one("#ind-tier", Static).update(
            f"[{MATRIX_MID}]GODZINA[/]\n"
            f"[bold {tier_color}]███ {tier.value} ███[/]\n"
            f"[{MATRIX_DARK}]UTC {now.hour:02d}:00 · tier serwera[/]"
        )

        # ── 2. PING 1h (avg TTFB → pressure level) ─────────────────────────
        ping_label, ping_color = _ping_pressure_level(ping_avg_ttfb)
        ping_detail = f"{ping_avg_ttfb:.0f} ms TTFB avg 1h" if ping_avg_ttfb > 0 else "brak pomiarów"
        self.query_one("#ind-ping", Static).update(
            f"[{MATRIX_MID}]PING 1h[/]\n"
            f"[bold {ping_color}]███ {ping_label} ███[/]\n"
            f"[{MATRIX_DARK}]{ping_detail}[/]"
        )

        # ── 3. BURN-RATE (taryfa) ──────────────────────────────────────────
        if reading is None:
            burn_color = MATRIX_DARK
            burn_label = "BRAK"
            burn_detail = "brak danych JSONL"
        else:
            burn_color = TARYFA_COLORS[reading.taryfa]
            burn_label = TARYFA_LABELS[reading.taryfa]
            if reading.baseline_used == "insufficient":
                burn_detail = f"zbieram dane ({reading.baseline_samples} prob.)"
            else:
                burn_detail = f"ratio {reading.ratio:.2f}× z{reading.z_score:+.1f}"
        self.query_one("#ind-burn", Static).update(
            f"[{MATRIX_MID}]BURN TOKENOW[/]\n"
            f"[bold {burn_color}]███ {burn_label} ███[/]\n"
            f"[{MATRIX_DARK}]{burn_detail}[/]"
        )

        # ── Linia szczegółowa + sparkline ──────────────────────────────────
        if reading is None:
            self.query_one("#taryfa-detail", Static).update(
                f"[{MATRIX_DARK}]taryfa: brak danych JSONL — uruchom sesje CC[/]"
            )
            self.query_one("#taryfa-spark", Static).update("")
            return

        detail = (
            f"[{MATRIX_MID}]teraz[/] [bold]{_fmt_tokens(reading.tokens_so_far)}[/]"
            f" [{MATRIX_MID}]/ base[/] {_fmt_tokens(int(reading.baseline_median))}  "
            f"[{MATRIX_MID}]proj[/] {_fmt_tokens(reading.projected_tokens)}  "
            f"[{MATRIX_MID}]dzis[/] [bold]{_fmt_tokens(reading.cumulative_today)}[/] "
            f"[{MATRIX_DARK}]${reading.cost_today:.2f}[/]  "
            f"[{MATRIX_MID}]base[/] [{MATRIX_DARK}]{reading.baseline_used}[/]  "
            f"[{MATRIX_MID}]sonar[/] "
            + (f"[bold {MATRIX_NEON}]●[/]" if sonar_on else f"[{MATRIX_DARK}]○[/]")
            + f" [{MATRIX_DARK}](s)[/]"
        )
        self.query_one("#taryfa-detail", Static).update(detail)

        spark_widget = self.query_one("#taryfa-spark", Static)
        sched = schedule_for_hour_range(weekend=False)

        # ── LEWO: 7 dni (baseline median per godzina UTC, bez dziś) ────────
        baseline_hourly = baseline_hourly or {}
        base_values: list[float] = []
        base_hollow: set[int] = set()
        for h in range(24):
            v = float(baseline_hourly.get(h, 0))
            base_values.append(v)
            if v <= 0:
                base_hollow.add(h)
        base_colors = [
            MATRIX_NEON if h == reading.hour else TIER_COLORS[sched[h]]
            for h in range(24)
        ]
        base_max = max(base_values) if base_values else 0.0
        base_max_label = f"{_fmt_tokens(int(base_max))} tok" if base_max > 0 else "— tok"
        left_lines = _render_chart(
            base_values, base_max, self.SPARK_ROWS, base_colors, sched, reading.hour,
            title="7 DNI  burn median", max_label=base_max_label,
            hollow=base_hollow, show_tier_dots=False,
        )

        # ── PRAWO: dziś (hourly_today) ─────────────────────────────────────
        if hourly_today:
            today_values: list[float] = []
            today_hollow: set[int] = set()
            for h in range(24):
                v = float(hourly_today.get(h, 0))
                today_values.append(v)
                if v <= 0 and h < reading.hour:
                    today_hollow.add(h)
            today_colors: list[str] = []
            for h in range(24):
                if h == reading.hour:
                    today_colors.append(burn_color)
                elif h > reading.hour:
                    today_colors.append(MATRIX_DARK)
                else:
                    today_colors.append(TIER_COLORS[sched[h]])
            today_max = max(today_values) if today_values else 0.0
            today_max_label = f"{_fmt_tokens(int(today_max))} tok" if today_max > 0 else "— tok"
            right_lines = _render_chart(
                today_values, today_max, self.SPARK_ROWS, today_colors, sched, reading.hour,
                title="DZIS  burn", max_label=today_max_label,
                hollow=today_hollow, show_tier_dots=False,
            )
        else:
            empty_values = [0.0] * 24
            empty_colors = [MATRIX_DARK] * 24
            right_lines = _render_chart(
                empty_values, 1.0, self.SPARK_ROWS, empty_colors, sched, reading.hour,
                title="DZIS  oczekiwanie", max_label="— tok",
                hollow=set(range(24)), show_tier_dots=False,
            )

        spark_widget.update("\n".join(_combine_lines(left_lines, right_lines)))


def _fmt_tokens(n: int) -> str:
    """Zwarty format tokenów (2.1k, 458k, 3.2M)."""
    if n < 1_000:
        return f"{n}"
    if n < 1_000_000:
        return f"{n / 1_000:.1f}k"
    return f"{n / 1_000_000:.2f}M"


class Thc24hHistogram(Static):
    """24h profil — wielowierszowy pionowy bar chart TTFB (7d baseline + dzis).

    Pełna doba UTC (0–23) jako 24 słupki × BAR_ROWS wierszy. Każda godzina
    zajmuje 2 kolumny terminala (słupek + separator) i wyrównuje się z osią
    godzin oraz pasem tierów pod spodem. Dla godzin bez pomiaru rysowana jest
    kropka (·), żeby doba pozostała pełna wizualnie mimo dziur w danych.
    """

    BAR_ROWS = 6  # wysokość wykresu (wielowierszowy pionowy bar chart)

    DEFAULT_CSS = f"""
    Thc24hHistogram {{
        height: auto;
        padding: 1 2;
        border: solid {MATRIX_MID_DARK};
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
    }}
    """

    def refresh_data(self, state: PingState | None) -> None:
        lines: list[str] = [
            f"[bold {MATRIX_NEON}]◈ 24H PROFIL[/]  "
            f"[{MATRIX_MID}]avg TTFB per godzina UTC[/]",
        ]
        if state is None:
            lines.append("")
            lines.append(f"[{MATRIX_DARK}](brak danych — uruchom `tost ping-collect`)[/]")
            self.update("\n".join(lines))
            return

        sched = schedule_for_hour_range(weekend=False)
        now = datetime.now(timezone.utc)
        now_hour = now.hour

        def _values_from(rows: list[dict]) -> tuple[list[float], set[int], float, float]:
            """Zwraca (values, hollow, max, avg_wazona_samplami)."""
            by_h = {r["hour"]: r for r in rows}
            vals: list[float] = []
            holl: set[int] = set()
            total_ms = 0.0
            total_samples = 0
            for h in range(24):
                row = by_h.get(h)
                v = float(row["avg_ttfb"] or 0.0) if row else 0.0
                vals.append(v)
                if v <= 0:
                    holl.add(h)
                if row:
                    s = int(row["sample_count"] or 0)
                    total_ms += v * s
                    total_samples += s
            avg = total_ms / total_samples if total_samples > 0 else 0.0
            return vals, holl, (max(vals) if vals else 0.0), avg

        # 7 DNI — avg TTFB per godzina ze wszystkich 7 dni (baseline)
        vals_7d, hollow_7d, max_7d, avg_7d = _values_from(state.get_hourly_summary(7, "api"))
        # 24 H — avg TTFB per godzina tylko z ostatnich 24h
        vals_24h, hollow_24h, max_24h, avg_24h = _values_from(state.get_hourly_summary(1, "api"))

        colors = [
            MATRIX_NEON if h == now_hour else TIER_COLORS[sched[h]]
            for h in range(24)
        ]

        # Ostatnie 20 pingow (oldest -> newest) — pobieramy przed obliczeniem
        # globalnej skali, żeby wszystkie 3 wykresy dzielily ten sam max.
        latest_pings = list(reversed(state.get_latest(20, target="api")))
        pings_ttfbs = [float(p.ttfb_ms) for p in latest_pings if p.ttfb_ms > 0]
        max_pings = max(pings_ttfbs, default=0.0)
        avg_pings = sum(pings_ttfbs) / len(pings_ttfbs) if pings_ttfbs else 0.0
        global_max = max(max_7d, max_24h, max_pings)

        def _label(v: float) -> str:
            return f"{v:>5.0f} ms" if v > 0 else "   — ms"

        left = _render_chart(
            vals_7d, global_max, self.BAR_ROWS, colors, sched, now_hour,
            title="7 DNI", summary_label=_label(avg_7d), hollow=hollow_7d,
        )
        middle = _render_chart(
            vals_24h, global_max, self.BAR_ROWS, colors, sched, now_hour,
            title="24 H", summary_label=_label(avg_24h), hollow=hollow_24h,
        )
        pings_title = f"OSTATNIE {len(latest_pings)}" if latest_pings else "OSTATNIE 20"
        pings_lines, pings_w = _render_pings_chart(
            latest_pings, self.BAR_ROWS, slots=20,
            title=pings_title, shared_max=global_max,
            summary_label=_label(avg_pings),
        )
        lines.extend(_combine_columns([
            (left, CHART_W),
            (middle, CHART_W),
            (pings_lines, pings_w),
        ]))

        # Legenda tierow
        now_tier = get_tier(now)
        legend = "  ".join(
            f"[{TIER_COLORS[t]}]●[/] [{MATRIX_MID}]{t.value}[/]"
            for t in (Tier.GREEN, Tier.YELLOW, Tier.ORANGE, Tier.RED)
        )
        lines.append("")
        lines.append(
            f"{legend}   "
            f"[{MATRIX_DARK}]biezacy tier UTC {now_hour:02d}:[/] "
            f"[bold {TIER_COLORS[now_tier]}]● {now_tier.value}[/]"
        )
        self.update("\n".join(lines))


class ThcRecentLog(DataTable):
    """DataTable ostatnich 50 pomiarów — Matrix styling."""

    DEFAULT_CSS = f"""
    ThcRecentLog {{
        height: 1fr;
        border: solid {MATRIX_MID_DARK};
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
    }}
    ThcRecentLog > .datatable--header {{
        background: {MATRIX_DEEP};
        color: {MATRIX_NEON};
        text-style: bold;
    }}
    ThcRecentLog > .datatable--cursor {{
        background: {MATRIX_DARK};
        color: {MATRIX_NEON};
    }}
    """

    def on_mount(self) -> None:
        self.add_columns(
            "Czas UTC", "Target", "Tier", "TTFB", "Connect", "DNS", "Total", "Status", "Błąd",
        )
        self.cursor_type = "row"
        self.zebra_stripes = False

    def refresh_data(self, state: PingState | None) -> None:
        self.clear()
        if state is None:
            return
        for p in state.get_recent(50):
            try:
                dt = datetime.fromisoformat(p.timestamp.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now(timezone.utc)
            tier = get_tier(dt)
            tier_color = TIER_COLORS[tier]
            self.add_row(
                p.timestamp[:19],
                p.target,
                f"[{tier_color}]● {tier.value}[/]",
                f"{p.ttfb_ms:.0f}",
                f"{p.connect_ms:.0f}",
                f"{p.dns_ms:.0f}",
                f"{p.total_ms:.0f}",
                str(p.status_code) if p.status_code else "ERR",
                p.error or "—",
            )


# ── App ────────────────────────────────────────────────────────────────────


class ThcApp(App):
    TITLE = "THC — TRAFFIC HOURS CONSOLE"
    SUB_TITLE = "Anthropic Server Load Radar"

    CSS = f"""
    Screen {{
        background: {MATRIX_VOID};
        color: {MATRIX_MID_LIGHT};
        layout: vertical;
    }}
    Header {{
        background: {MATRIX_DEEP};
        color: {MATRIX_NEON};
    }}
    Footer {{
        background: {MATRIX_DEEP};
        color: {MATRIX_MID};
    }}
    #top-row {{
        height: 14;
    }}
    #clock-box    {{ width: 2fr; }}
    #ping-box     {{ width: 1fr; }}
    #tier-box     {{ width: 1fr; }}
    #taryfa-box   {{ height: 16; }}
    #hist-box     {{ height: auto; }}
    #recent-log   {{ height: 1fr; }}
    """

    BINDINGS = [
        Binding("q", "quit", "Wyjdz"),
        Binding("r", "refresh_now", "Odswiez"),
        Binding("ctrl+r", "reload_tiers", "Reload TOML"),
        Binding("s", "toggle_sonar", "Sonar on/off"),
    ]

    # Class-level default — gwarantuje istnienie przed on_mount (on_unmount
    # po nieudanym mount nie wyrzuci AttributeError).
    _taryfa_state: TaryfaState | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="top-row"):
            yield ThcClock(id="clock-box")
            yield ThcPingPanel(id="ping-box")
            yield ThcTierStats(id="tier-box")
        yield ThcTaryfaPanel(id="taryfa-box")
        yield Thc24hHistogram(id="hist-box")
        yield ThcRecentLog(id="recent-log")
        yield Footer()

    def on_mount(self) -> None:
        # Otwarty raz na cały czas życia aplikacji (skan inkrementalny po offsetach)
        try:
            self._taryfa_state = TaryfaState()
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"Taryfa state init failed: {e}")
            self._taryfa_state = None
        self.action_refresh_now()
        self.set_interval(REFRESH_INTERVAL, self.action_refresh_now)

    def on_unmount(self) -> None:
        if self._taryfa_state is not None:
            try:
                self._taryfa_state.close()
            except Exception:  # noqa: BLE001
                pass

    def _open_state(self) -> PingState | None:
        if not DEFAULT_PING_DB.exists():
            return None
        return PingState(DEFAULT_PING_DB)

    def _refresh_taryfa(self, ping_state: PingState | None = None) -> None:
        panel = self.query_one(ThcTaryfaPanel)
        ping_avg = 0.0
        if ping_state is not None:
            try:
                rolling = ping_state.get_rolling_avg_minutes(60, "api")
                ping_avg = float(rolling.get("avg_ttfb") or 0.0)
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"Ping rolling avg failed: {e}")
        if self._taryfa_state is None:
            panel.refresh_data(None, None, None, ping_avg, sonar_is_enabled())
            return
        try:
            scan_new_records(self._taryfa_state)
            reading = compute_tariff(self._taryfa_state)
            today_hourly = self._taryfa_state.get_hourly_for_day(reading.date)
            baseline_hourly = _baseline_hourly_medians(self._taryfa_state, reading.date)
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"Taryfa refresh failed: {e}")
            panel.refresh_data(None, None, None, ping_avg, sonar_is_enabled())
            return
        panel.refresh_data(
            reading, today_hourly, baseline_hourly, ping_avg, sonar_is_enabled(),
        )

    def action_refresh_now(self) -> None:
        state = self._open_state()
        try:
            self.query_one(ThcClock).refresh_data()
            self.query_one(ThcPingPanel).refresh_data(state)
            self.query_one(ThcTierStats).refresh_data(state)
            self.query_one(Thc24hHistogram).refresh_data(state)
            self.query_one(ThcRecentLog).refresh_data(state)
            self._refresh_taryfa(state)
        finally:
            if state is not None:
                state.close()

    def action_reload_tiers(self) -> None:
        reload_schedule()
        reload_thresholds()
        self.action_refresh_now()
        self.notify("Progi przeladowane (thc_tiers.toml + taryfa_thresholds.toml)")

    def action_toggle_sonar(self) -> None:
        new_state = sonar_toggle()
        self._refresh_taryfa()
        self.notify(f"Sonar {'WLACZONY' if new_state else 'WYLACZONY'}")


def main() -> None:
    ThcApp().run()


if __name__ == "__main__":
    main()
