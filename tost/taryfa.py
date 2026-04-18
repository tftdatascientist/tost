"""Taryfa — detektor tempa zużycia tokenów vs. 7-dniowy baseline godziny doby.

Algorytm:
    1. Skanuj JSONL `~/.claude/projects/*.jsonl` inkrementalnie (byte-offset),
       agreguj tokeny do kubełków (date, hour UTC).
    2. Dla bieżącej godziny H policz:
         tokens_so_far         — tokeny od `hh:00` do teraz
         expected_so_far       — median(baseline_H_last_7_days) × elapsed_fraction
         ratio                 = tokens_so_far / expected_so_far
         projected             = tokens_so_far / elapsed_fraction (ekstrapolacja)
         z-score               = (projected − median) / (1.4826 × MAD)
    3. Taryfa = MAX severity z [ratio-based, z-based, p90-based]:
         ZIELONA  — tempo normalne
         ŻÓŁTA    — podwyższone
         POMARAŃCZOWA — wyraźnie szybciej niż zwykle
         CZERWONA — anomalia (risk wyczerpania limitu)

MAD zamiast stdev — odporniejszy na outliery (1 dzień ze skokiem nie psuje baseline).
Ratio + z-score łączone, bo:
    - ratio wyłapuje systematyczne przesunięcia (zawsze szybciej o 50%)
    - z-score wyłapuje rzadkie skoki (poza ogonem rozkładu)

Fallback: < min_samples próbek dla godziny → użyj wszystkich kubełków
z ostatnich 7 dni jako baselinu globalnego. < min_samples globalnie → ZIELONA.

State: `~/.claude/tost_taryfa.db` (SQLite WAL).
Progi: `tost/taryfa_thresholds.toml` (edytowalne bez kodu).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from tost.cost import calculate_cost
from tost.jsonl_scanner import CLAUDE_PROJECTS_DIR, MAX_FILE_BYTES, extract_usage

log = logging.getLogger("tost.taryfa")

DEFAULT_TARYFA_DB = Path.home() / ".claude" / "tost_taryfa.db"
TARYFA_THRESHOLDS_FILE = Path(__file__).parent / "taryfa_thresholds.toml"


# ── Enum i kolory ──────────────────────────────────────────────────────────


class Taryfa(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


TARYFA_COLORS: dict[Taryfa, str] = {
    Taryfa.GREEN:  "#39FF14",
    Taryfa.YELLOW: "#FFD700",
    Taryfa.ORANGE: "#FF8800",
    Taryfa.RED:    "#FF3030",
}

# Etykiety po polsku (dla Notion + TUI)
TARYFA_LABELS: dict[Taryfa, str] = {
    Taryfa.GREEN:  "ZIELONA",
    Taryfa.YELLOW: "ZOLTA",
    Taryfa.ORANGE: "POMARANCZOWA",
    Taryfa.RED:    "CZERWONA",
}

# Kolory Notion (dla select) — muszą być z zamkniętej listy Notion
TARYFA_NOTION_COLORS: dict[Taryfa, str] = {
    Taryfa.GREEN:  "green",
    Taryfa.YELLOW: "yellow",
    Taryfa.ORANGE: "orange",
    Taryfa.RED:    "red",
}

_SEVERITY: dict[Taryfa, int] = {
    Taryfa.GREEN: 0, Taryfa.YELLOW: 1, Taryfa.ORANGE: 2, Taryfa.RED: 3,
}


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class HourlyBucket:
    date: str                # YYYY-MM-DD UTC
    hour: int                # 0-23 UTC
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    message_count: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens
            + self.cache_read_tokens + self.cache_creation_tokens
        )


@dataclass
class TaryfaReading:
    taryfa: Taryfa
    ratio: float                    # tokens_so_far / expected_so_far
    z_score: float                  # MAD-based
    projected_tokens: int           # ekstrapolacja tokens_so_far do pelnej godziny
    tokens_so_far: int
    cost_so_far: float
    baseline_median: float
    baseline_p75: float
    baseline_p90: float
    baseline_samples: int
    baseline_used: str              # "hour-of-day" | "all-day-fallback" | "insufficient"
    cumulative_today: int
    cost_today: float
    elapsed_fraction: float         # [0, 1]
    hour: int
    date: str

    @property
    def color(self) -> str:
        return TARYFA_COLORS[self.taryfa]

    @property
    def label(self) -> str:
        return TARYFA_LABELS[self.taryfa]


# ── Progi (TOML, z fallbackiem) ────────────────────────────────────────────


DEFAULT_THRESHOLDS: dict[str, float] = {
    "baseline_days":        7.0,
    "min_samples":          5.0,
    "green_ratio_max":      1.0,
    "yellow_ratio_max":     1.5,
    "orange_ratio_max":     2.5,
    "green_z_max":          1.0,
    "yellow_z_max":         2.0,
    "orange_z_max":         3.0,
    "p90_multiplier_red":   2.0,
    "min_elapsed_seconds":  120.0,
}

_THRESHOLDS_CACHE: dict[str, float] | None = None


def load_thresholds() -> dict[str, float]:
    global _THRESHOLDS_CACHE
    if _THRESHOLDS_CACHE is not None:
        return _THRESHOLDS_CACHE
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            _THRESHOLDS_CACHE = dict(DEFAULT_THRESHOLDS)
            return _THRESHOLDS_CACHE

    result = dict(DEFAULT_THRESHOLDS)
    if TARYFA_THRESHOLDS_FILE.exists():
        try:
            with TARYFA_THRESHOLDS_FILE.open("rb") as f:
                data = tomllib.load(f)
            for k, v in data.items():
                if k in result:
                    try:
                        result[k] = float(v)
                    except (TypeError, ValueError):
                        continue
        except Exception as e:  # TOML parse / IO
            log.warning("Blad wczytywania taryfa_thresholds.toml: %s — fallback", e)
    _THRESHOLDS_CACHE = result
    return result


def reload_thresholds() -> None:
    global _THRESHOLDS_CACHE
    _THRESHOLDS_CACHE = None


# ── SQLite state ───────────────────────────────────────────────────────────


class TaryfaState:
    """Kubełki godzinowe + offsety plików JSONL + mapowanie Notion."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS taryfa_hourly (
        date TEXT NOT NULL,
        hour INTEGER NOT NULL,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens INTEGER NOT NULL DEFAULT 0,
        cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0,
        message_count INTEGER NOT NULL DEFAULT 0,
        last_updated TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (date, hour)
    );
    CREATE INDEX IF NOT EXISTS idx_taryfa_hour ON taryfa_hourly(hour);
    CREATE INDEX IF NOT EXISTS idx_taryfa_date ON taryfa_hourly(date);

    CREATE TABLE IF NOT EXISTS taryfa_file_offsets (
        file_path TEXT PRIMARY KEY,
        byte_offset INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS taryfa_notion_pages (
        date TEXT NOT NULL,
        hour INTEGER NOT NULL,
        page_id TEXT NOT NULL,
        last_synced_total INTEGER NOT NULL DEFAULT 0,
        last_synced_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (date, hour)
    );

    CREATE TABLE IF NOT EXISTS taryfa_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """

    def __init__(self, db_path: str | Path = DEFAULT_TARYFA_DB) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    # ── konfiguracja (np. cached database_id Notion) ───────────────────────

    def get_config(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM taryfa_config WHERE key=?", (key,),
        ).fetchone()
        return row[0] if row else None

    def set_config(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO taryfa_config(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ── offsety JSONL ──────────────────────────────────────────────────────

    def get_offset(self, file_path: str) -> int:
        row = self.conn.execute(
            "SELECT byte_offset FROM taryfa_file_offsets WHERE file_path=?",
            (file_path,),
        ).fetchone()
        return int(row[0]) if row else 0

    def set_offset(self, file_path: str, offset: int) -> None:
        self.conn.execute(
            "INSERT INTO taryfa_file_offsets(file_path, byte_offset) VALUES(?,?) "
            "ON CONFLICT(file_path) DO UPDATE SET byte_offset=excluded.byte_offset",
            (file_path, offset),
        )

    # ── kubełki ────────────────────────────────────────────────────────────

    def add_to_bucket(
        self,
        date: str,
        hour: int,
        input_t: int,
        output_t: int,
        cache_read_t: int,
        cache_creation_t: int,
        cost: float,
        now_iso: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO taryfa_hourly(
                date, hour, input_tokens, output_tokens,
                cache_read_tokens, cache_creation_tokens,
                cost_usd, message_count, last_updated
            ) VALUES(?,?,?,?,?,?,?,1,?)
            ON CONFLICT(date, hour) DO UPDATE SET
                input_tokens          = input_tokens          + excluded.input_tokens,
                output_tokens         = output_tokens         + excluded.output_tokens,
                cache_read_tokens     = cache_read_tokens     + excluded.cache_read_tokens,
                cache_creation_tokens = cache_creation_tokens + excluded.cache_creation_tokens,
                cost_usd              = cost_usd              + excluded.cost_usd,
                message_count         = message_count         + 1,
                last_updated          = excluded.last_updated
            """,
            (date, hour, input_t, output_t, cache_read_t, cache_creation_t, cost, now_iso),
        )

    def get_bucket(self, date: str, hour: int) -> HourlyBucket | None:
        row = self.conn.execute(
            """
            SELECT input_tokens, output_tokens, cache_read_tokens,
                   cache_creation_tokens, cost_usd, message_count
            FROM taryfa_hourly WHERE date=? AND hour=?
            """,
            (date, hour),
        ).fetchone()
        if not row:
            return None
        return HourlyBucket(
            date=date, hour=hour,
            input_tokens=row[0], output_tokens=row[1],
            cache_read_tokens=row[2], cache_creation_tokens=row[3],
            cost_usd=row[4], message_count=row[5],
        )

    def get_baseline_for_hour(
        self, hour: int, days: int, exclude_date: str,
    ) -> list[int]:
        """Totale tokenów dla danej godziny doby z ostatnich N dni (bez dziś)."""
        rows = self.conn.execute(
            """
            SELECT input_tokens + output_tokens
                 + cache_read_tokens + cache_creation_tokens AS total
            FROM taryfa_hourly
            WHERE hour = ?
              AND date != ?
              AND date >= date(?, ?)
            """,
            (hour, exclude_date, exclude_date, f"-{days} days"),
        ).fetchall()
        return [int(r[0]) for r in rows if r[0] and r[0] > 0]

    def get_baseline_all_hours(
        self, days: int, exclude_date: str,
    ) -> list[int]:
        """Totale tokenów/godzinę z ostatnich N dni (bez dziś) — fallback."""
        rows = self.conn.execute(
            """
            SELECT input_tokens + output_tokens
                 + cache_read_tokens + cache_creation_tokens AS total
            FROM taryfa_hourly
            WHERE date != ?
              AND date >= date(?, ?)
            """,
            (exclude_date, exclude_date, f"-{days} days"),
        ).fetchall()
        return [int(r[0]) for r in rows if r[0] and r[0] > 0]

    def get_day_totals(self, date: str) -> tuple[int, float]:
        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(input_tokens + output_tokens
                           + cache_read_tokens + cache_creation_tokens), 0),
                COALESCE(SUM(cost_usd), 0)
            FROM taryfa_hourly WHERE date = ?
            """,
            (date,),
        ).fetchone()
        return (int(row[0] or 0), float(row[1] or 0.0))

    def get_hourly_for_day(self, date: str) -> dict[int, int]:
        """{hour: total_tokens} dla podanego dnia — do sparkline."""
        rows = self.conn.execute(
            """
            SELECT hour,
                   input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens
            FROM taryfa_hourly WHERE date = ?
            """,
            (date,),
        ).fetchall()
        return {int(r[0]): int(r[1]) for r in rows}

    def get_dirty_buckets_since(self, cutoff_iso: str) -> list[HourlyBucket]:
        """Kubełki zmodyfikowane po cutoff_iso (do syncu Notion)."""
        rows = self.conn.execute(
            """
            SELECT date, hour, input_tokens, output_tokens,
                   cache_read_tokens, cache_creation_tokens,
                   cost_usd, message_count
            FROM taryfa_hourly
            WHERE last_updated > ?
            ORDER BY date, hour
            """,
            (cutoff_iso,),
        ).fetchall()
        return [
            HourlyBucket(
                date=r[0], hour=r[1],
                input_tokens=r[2], output_tokens=r[3],
                cache_read_tokens=r[4], cache_creation_tokens=r[5],
                cost_usd=r[6], message_count=r[7],
            )
            for r in rows
        ]

    # ── Notion page mapping ────────────────────────────────────────────────

    def get_notion_page(self, date: str, hour: int) -> tuple[str, int] | None:
        row = self.conn.execute(
            "SELECT page_id, last_synced_total FROM taryfa_notion_pages "
            "WHERE date=? AND hour=?",
            (date, hour),
        ).fetchone()
        if not row:
            return None
        return (row[0], int(row[1]))

    def set_notion_page(
        self, date: str, hour: int, page_id: str, total: int, synced_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO taryfa_notion_pages(date, hour, page_id, last_synced_total, last_synced_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(date, hour) DO UPDATE SET
                page_id=excluded.page_id,
                last_synced_total=excluded.last_synced_total,
                last_synced_at=excluded.last_synced_at
            """,
            (date, hour, page_id, total, synced_at),
        )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# ── Skaner JSONL (incremental via byte-offset) ─────────────────────────────


def scan_new_records(
    state: TaryfaState,
    root: Path | None = None,
) -> int:
    """Inkrementalne parsowanie JSONL — tylko nowe bajty od ostatniego pass.

    JSONL Claude Code jest append-only, więc offset w bajtach wystarczy.
    Jeśli plik skurczył się (rotacja/recreate), resetujemy offset do 0.

    Returns: liczba nowych assistant-messages zagregowanych.
    """
    base = root or CLAUDE_PROJECTS_DIR
    if not base.is_dir():
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    total = 0

    for project_dir in sorted(base.iterdir()):
        if not project_dir.is_dir():
            continue
        for file_path in sorted(project_dir.glob("*.jsonl")):
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                log.debug("Taryfa: pomijam %s (> %d B)", file_path, MAX_FILE_BYTES)
                continue

            key = str(file_path)
            offset = state.get_offset(key)
            if offset > size:
                # plik skurczony → reset
                offset = 0
            if offset == size:
                continue

            new_offset = offset
            try:
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    while True:
                        line_bytes = f.readline()
                        if not line_bytes:
                            break
                        new_offset = f.tell()

                        try:
                            line = line_bytes.decode("utf-8", errors="replace").strip()
                        except Exception:  # noqa: BLE001
                            continue
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        usage = extract_usage(record)
                        if not usage:
                            continue

                        ts = record.get("timestamp")
                        if not isinstance(ts, str) or len(ts) < 10:
                            continue
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except ValueError:
                            continue
                        dt_utc = dt.astimezone(timezone.utc)
                        date = dt_utc.strftime("%Y-%m-%d")
                        hour = dt_utc.hour

                        cost = calculate_cost(
                            model=usage["model"],
                            input_tokens=usage["input_tokens"],
                            output_tokens=usage["output_tokens"],
                            cache_read_tokens=usage["cache_read_tokens"],
                            cache_creation_tokens=usage["cache_creation_tokens"],
                        )
                        state.add_to_bucket(
                            date, hour,
                            usage["input_tokens"], usage["output_tokens"],
                            usage["cache_read_tokens"], usage["cache_creation_tokens"],
                            cost, now_iso,
                        )
                        total += 1
            except OSError as e:
                log.debug("Taryfa: blad czytania %s: %s", file_path, e)
                continue

            state.set_offset(key, new_offset)

    state.commit()
    return total


# ── Algorytm taryfy ────────────────────────────────────────────────────────


def _percentile(sorted_vals: list[int], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = p * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _mad(values: list[int], median: float) -> float:
    """Median Absolute Deviation (odporniejszy estymator rozrzutu niż stdev)."""
    if not values:
        return 0.0
    deviations = [abs(v - median) for v in values]
    deviations.sort()
    return float(statistics.median(deviations))


def _tariff_from_ratio(
    ratio: float, projected: int, p90: float, thr: dict[str, float],
) -> Taryfa:
    # Dodatkowy warunek CZERWONEJ: projekcja >> p90
    if p90 > 0 and projected > thr["p90_multiplier_red"] * p90:
        return Taryfa.RED
    if ratio <= thr["green_ratio_max"]:
        return Taryfa.GREEN
    if ratio <= thr["yellow_ratio_max"]:
        return Taryfa.YELLOW
    if ratio <= thr["orange_ratio_max"]:
        return Taryfa.ORANGE
    return Taryfa.RED


def _tariff_from_z(z: float, thr: dict[str, float]) -> Taryfa:
    if z <= thr["green_z_max"]:
        return Taryfa.GREEN
    if z <= thr["yellow_z_max"]:
        return Taryfa.YELLOW
    if z <= thr["orange_z_max"]:
        return Taryfa.ORANGE
    return Taryfa.RED


def compute_tariff(
    state: TaryfaState,
    now: datetime | None = None,
    thresholds: dict[str, float] | None = None,
) -> TaryfaReading:
    """Główna funkcja: zwróć bieżący TaryfaReading dla `now` (UTC)."""
    thr = thresholds or load_thresholds()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    date = now_utc.strftime("%Y-%m-%d")
    hour = now_utc.hour

    bucket = state.get_bucket(date, hour)
    tokens_so_far = bucket.total_tokens if bucket else 0
    cost_so_far = bucket.cost_usd if bucket else 0.0

    elapsed_sec = now_utc.minute * 60 + now_utc.second
    elapsed_fraction = max(elapsed_sec / 3600.0, 1.0 / 3600.0)  # >=1s

    today_total, today_cost = state.get_day_totals(date)

    days = int(thr.get("baseline_days", 7))
    min_samples = int(thr.get("min_samples", 5))

    # 1) Baseline dla tej godziny doby
    baseline = state.get_baseline_for_hour(hour, days, date)
    baseline_used = "hour-of-day"
    if len(baseline) < min_samples:
        # 2) Fallback: wszystkie godziny z ostatnich N dni
        baseline = state.get_baseline_all_hours(days, date)
        baseline_used = "all-day-fallback"

    if len(baseline) < min_samples:
        # 3) Za mało danych — zwróć ZIELONĄ
        return TaryfaReading(
            taryfa=Taryfa.GREEN, ratio=0.0, z_score=0.0,
            projected_tokens=0, tokens_so_far=tokens_so_far, cost_so_far=cost_so_far,
            baseline_median=0.0, baseline_p75=0.0, baseline_p90=0.0,
            baseline_samples=len(baseline), baseline_used="insufficient",
            cumulative_today=today_total, cost_today=today_cost,
            elapsed_fraction=elapsed_fraction, hour=hour, date=date,
        )

    sorted_b = sorted(baseline)
    median = float(statistics.median(sorted_b))
    mad = _mad(sorted_b, median)
    # Dolny clamp na MAD — gdy wszystkie wartości identyczne, mad=0; bierzemy 10% mediany
    mad_scaled = 1.4826 * mad if mad > 0 else max(median * 0.1, 1.0)

    p75 = _percentile(sorted_b, 0.75)
    p90 = _percentile(sorted_b, 0.90)

    # Projekcja: skaluj do pełnej godziny jeśli minęło wystarczająco czasu
    min_elapsed = float(thr.get("min_elapsed_seconds", 120))
    if elapsed_sec >= min_elapsed and elapsed_fraction > 0:
        projected = int(tokens_so_far / elapsed_fraction)
    else:
        projected = tokens_so_far

    expected_so_far = median * elapsed_fraction
    ratio = tokens_so_far / expected_so_far if expected_so_far > 0 else 0.0
    z_score = (projected - median) / mad_scaled if mad_scaled > 0 else 0.0

    # Gdy za mało czasu upłynęło — nie straszymy ratio, wymuszamy GREEN
    if elapsed_sec < min_elapsed:
        taryfa = Taryfa.GREEN
    else:
        t_ratio = _tariff_from_ratio(ratio, projected, p90, thr)
        t_z = _tariff_from_z(z_score, thr)
        taryfa = max([t_ratio, t_z], key=lambda t: _SEVERITY[t])

    return TaryfaReading(
        taryfa=taryfa, ratio=ratio, z_score=z_score,
        projected_tokens=projected, tokens_so_far=tokens_so_far, cost_so_far=cost_so_far,
        baseline_median=median, baseline_p75=p75, baseline_p90=p90,
        baseline_samples=len(baseline), baseline_used=baseline_used,
        cumulative_today=today_total, cost_today=today_cost,
        elapsed_fraction=elapsed_fraction, hour=hour, date=date,
    )


def refresh_and_read(
    state: TaryfaState | None = None,
    now: datetime | None = None,
) -> TaryfaReading:
    """Convenience: scan JSONL + compute tariff w jednym wywołaniu."""
    own_state = state is None
    st = state or TaryfaState()
    try:
        scan_new_records(st)
        return compute_tariff(st, now)
    finally:
        if own_state:
            st.close()
