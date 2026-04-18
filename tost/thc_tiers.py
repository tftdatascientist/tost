"""THC — strefy poziomu zagrożenia (Traffic Hours tiers).

Dobę dzielimy na 4 tiery wg obciążenia serwerów Anthropic:
    GREEN   — USA śpi, EU/Asia mało aktywne
    YELLOW  — EU pracuje, US East się rozkręca
    ORANGE  — przejściowe (EU + US East/West)
    RED     — peak: overlap US East + US West + końcówka EU

Weekendy są zawsze GREEN.

Progi konfigurowane w `thc_tiers.toml` (edytowalne bez dotykania kodu).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

TIERS_FILE = Path(__file__).parent / "thc_tiers.toml"


class Tier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"

    @property
    def color(self) -> str:
        return TIER_COLORS[self]

    @property
    def symbol(self) -> str:
        return "●"


TIER_COLORS: dict[Tier, str] = {
    Tier.GREEN:  "#39FF14",   # Matrix neon
    Tier.YELLOW: "#FFD700",
    Tier.ORANGE: "#FF8800",
    Tier.RED:    "#FF3030",
}


# Domyślny harmonogram dni roboczych (godzina UTC → tier)
DEFAULT_WEEKDAY_SCHEDULE: dict[int, Tier] = {
    **{h: Tier.GREEN  for h in range(0, 12)},
    **{h: Tier.YELLOW for h in (12, 13)},
    14: Tier.ORANGE,
    **{h: Tier.RED    for h in range(15, 20)},
    **{h: Tier.ORANGE for h in (20, 21)},
    **{h: Tier.YELLOW for h in (22, 23)},
}


_SCHEDULE_CACHE: dict[int, Tier] | None = None


def _load_schedule() -> dict[int, Tier]:
    """Wczytaj harmonogram z TOML; fallback na DEFAULT_WEEKDAY_SCHEDULE."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return dict(DEFAULT_WEEKDAY_SCHEDULE)

    if not TIERS_FILE.exists():
        return dict(DEFAULT_WEEKDAY_SCHEDULE)

    with TIERS_FILE.open("rb") as f:
        data = tomllib.load(f)

    schedule: dict[int, Tier] = {}
    for hour_str, tier_str in (data.get("weekday") or {}).items():
        try:
            hour = int(hour_str)
            if 0 <= hour <= 23:
                schedule[hour] = Tier(str(tier_str).upper())
        except (ValueError, KeyError):
            continue

    for h in range(24):
        schedule.setdefault(h, Tier.GREEN)
    return schedule


def _schedule() -> dict[int, Tier]:
    global _SCHEDULE_CACHE
    if _SCHEDULE_CACHE is None:
        _SCHEDULE_CACHE = _load_schedule()
    return _SCHEDULE_CACHE


def reload_schedule() -> None:
    """Wymuś ponowne wczytanie TOML (po edycji pliku)."""
    global _SCHEDULE_CACHE
    _SCHEDULE_CACHE = None


def _is_weekend(dt_utc: datetime) -> bool:
    return dt_utc.weekday() >= 5


def get_tier(dt_utc: datetime) -> Tier:
    """Tier dla zadanej chwili (w UTC). Weekendy = GREEN."""
    if _is_weekend(dt_utc):
        return Tier.GREEN
    return _schedule().get(dt_utc.hour, Tier.GREEN)


def next_tier_change(dt_utc: datetime) -> tuple[Tier, datetime]:
    """(nowy_tier, moment_UTC) najbliższej zmiany strefy.

    Iteruje po pełnych godzinach. Lookahead 7 dni (pokrywa weekend).
    """
    current = get_tier(dt_utc)
    probe = dt_utc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(24 * 7):
        tier = get_tier(probe)
        if tier != current:
            return tier, probe
        probe += timedelta(hours=1)
    return current, probe


def next_red_start(dt_utc: datetime) -> datetime:
    """Moment startu najbliższego okna RED.

    Gdy obecnie w RED → zwraca start *kolejnego* okna RED (po wyjściu).
    """
    probe = dt_utc.replace(minute=0, second=0, microsecond=0)
    if get_tier(probe) == Tier.RED:
        while get_tier(probe) == Tier.RED:
            probe += timedelta(hours=1)
    while get_tier(probe) != Tier.RED:
        probe += timedelta(hours=1)
    return probe


def red_window_end(dt_utc: datetime) -> datetime | None:
    """Moment wyjścia z obecnego RED — None jeśli nie jesteśmy w RED."""
    if get_tier(dt_utc) != Tier.RED:
        return None
    probe = dt_utc.replace(minute=0, second=0, microsecond=0)
    while get_tier(probe) == Tier.RED:
        probe += timedelta(hours=1)
    return probe


def schedule_for_hour_range(weekend: bool = False) -> list[Tier]:
    """24 tiery (indeks = godzina UTC). Dla wykresu/legend."""
    if weekend:
        return [Tier.GREEN] * 24
    s = _schedule()
    return [s.get(h, Tier.GREEN) for h in range(24)]
