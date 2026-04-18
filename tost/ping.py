"""Ping — monitoring latencji API Anthropic.

Mierzy czas odpowiedzi HEAD do api.anthropic.com co 5 minut (bez API key),
zapisuje do SQLite, synchronizuje hourly aggregaty do Notion.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

log = logging.getLogger("tost.ping")

ANTHROPIC_API = "https://api.anthropic.com/v1"
DEFAULT_PING_DB = Path.home() / ".claude" / "tost_ping.db"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ── Config & data ──────────────────────────────────────────────────────────


PING_TARGETS = [
    ("api", "https://api.anthropic.com/v1/messages"),
    ("status", "https://status.anthropic.com"),
]


@dataclass
class PingConfig:
    ping_interval: float = 300.0         # 5 minut
    notion_sync_interval: float = 1800.0  # 30 minut (hourly aggs)
    thc_sync_interval: float = 900.0     # 15 minut (THC 15-min buckets)
    notion_token: str | None = None
    ping_db_id: str | None = None
    thc_db_id: str | None = None         # osobna baza THC (15-min agregaty)


@dataclass
class PingResult:
    timestamp: str       # ISO 8601 UTC
    target: str          # "api" lub "status"
    total_ms: float      # cały request
    dns_ms: float        # DNS lookup
    connect_ms: float    # TCP + TLS connect
    ttfb_ms: float       # Time To First Byte — opóźnienie serwera Anthropic
    status_code: int
    error: str | None
    day_of_week: int     # 0=Monday
    hour: int            # 0-23 UTC


# ── SQLite state ───────────────────────────────────────────────────────────


class PingState:
    """Persists ping measurements in SQLite."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS ping_raw (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT 'api',
        total_ms REAL NOT NULL,
        dns_ms REAL NOT NULL DEFAULT 0,
        connect_ms REAL NOT NULL DEFAULT 0,
        ttfb_ms REAL NOT NULL DEFAULT 0,
        status_code INTEGER NOT NULL,
        error TEXT,
        day_of_week INTEGER NOT NULL,
        hour INTEGER NOT NULL,
        synced_to_notion INTEGER NOT NULL DEFAULT 0,
        synced_to_thc INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_ping_raw_ts ON ping_raw(timestamp);
    CREATE INDEX IF NOT EXISTS idx_ping_raw_synced ON ping_raw(synced_to_notion);
    CREATE INDEX IF NOT EXISTS idx_ping_raw_synced_thc ON ping_raw(synced_to_thc);
    CREATE INDEX IF NOT EXISTS idx_ping_raw_target ON ping_raw(target);
    """

    # Kolumny dodawane przez migracje (jeśli brakuje w istniejącej tabeli)
    ADDABLE_COLUMNS = [
        ("total_ms",       "ALTER TABLE ping_raw ADD COLUMN total_ms REAL NOT NULL DEFAULT 0"),
        ("dns_ms",         "ALTER TABLE ping_raw ADD COLUMN dns_ms REAL NOT NULL DEFAULT 0"),
        ("connect_ms",     "ALTER TABLE ping_raw ADD COLUMN connect_ms REAL NOT NULL DEFAULT 0"),
        ("ttfb_ms",        "ALTER TABLE ping_raw ADD COLUMN ttfb_ms REAL NOT NULL DEFAULT 0"),
        ("synced_to_thc",  "ALTER TABLE ping_raw ADD COLUMN synced_to_thc INTEGER NOT NULL DEFAULT 0"),
    ]

    def __init__(self, db_path: str | Path) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Utwórz tabelę lub migruj ze starego schematu."""
        # Sprawdź czy tabela istnieje
        exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ping_raw'"
        ).fetchone()

        if not exists:
            # Nowa baza — utwórz od zera
            self.conn.executescript(self.SCHEMA)
            self._has_legacy_column = False
            return

        # Tabela istnieje — sprawdź czy ma stare kolumny
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(ping_raw)").fetchall()}
        self._has_legacy_column = "latency_ms" in cols

        # Dodaj brakujące kolumny
        for col_name, sql in self.ADDABLE_COLUMNS:
            if col_name not in cols:
                self.conn.execute(sql)
                log.info("Migracja: dodano kolumnę %s", col_name)

        # Migracja latency_ms → total_ms (stare dane)
        if "latency_ms" in cols:
            self.conn.execute(
                "UPDATE ping_raw SET total_ms = latency_ms "
                "WHERE total_ms = 0 AND latency_ms IS NOT NULL AND latency_ms > 0"
            )

        # Utwórz indeksy jeśli brakuje
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_ping_raw_ts ON ping_raw(timestamp);
            CREATE INDEX IF NOT EXISTS idx_ping_raw_synced ON ping_raw(synced_to_notion);
            CREATE INDEX IF NOT EXISTS idx_ping_raw_synced_thc ON ping_raw(synced_to_thc);
            CREATE INDEX IF NOT EXISTS idx_ping_raw_target ON ping_raw(target);
        """)

    def insert_result(self, r: PingResult) -> None:
        if self._has_legacy_column:
            # Stary schemat z latency_ms — wpisz total_ms też jako latency_ms
            self.conn.execute(
                "INSERT INTO ping_raw(timestamp, target, total_ms, dns_ms, "
                "connect_ms, ttfb_ms, latency_ms, status_code, error, "
                "day_of_week, hour, synced_to_notion) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
                (r.timestamp, r.target, r.total_ms, r.dns_ms, r.connect_ms,
                 r.ttfb_ms, r.total_ms, r.status_code, r.error,
                 r.day_of_week, r.hour),
            )
        else:
            self.conn.execute(
                "INSERT INTO ping_raw(timestamp, target, total_ms, dns_ms, "
                "connect_ms, ttfb_ms, status_code, error, day_of_week, hour, "
                "synced_to_notion) VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                (r.timestamp, r.target, r.total_ms, r.dns_ms, r.connect_ms,
                 r.ttfb_ms, r.status_code, r.error, r.day_of_week, r.hour),
            )
        self.conn.commit()

    def get_latest(self, n: int = 1, target: str = "api") -> list[PingResult]:
        rows = self.conn.execute(
            "SELECT timestamp, target, total_ms, dns_ms, connect_ms, ttfb_ms, "
            "status_code, error, day_of_week, hour "
            "FROM ping_raw WHERE target = ? ORDER BY id DESC LIMIT ?",
            (target, n),
        ).fetchall()
        return [
            PingResult(
                timestamp=r[0], target=r[1], total_ms=r[2], dns_ms=r[3],
                connect_ms=r[4], ttfb_ms=r[5], status_code=r[6],
                error=r[7], day_of_week=r[8], hour=r[9],
            )
            for r in rows
        ]

    def get_unsynced_hourly_aggs(self) -> list[dict]:
        """Agregaty godzinowe z niesynchronizowanych pomiarów."""
        rows = self.conn.execute("""
            SELECT
                date(timestamp) AS day,
                hour,
                day_of_week,
                target,
                COUNT(*) AS sample_count,
                ROUND(AVG(total_ms), 1) AS avg_total,
                ROUND(MIN(total_ms), 1) AS min_total,
                ROUND(MAX(total_ms), 1) AS max_total,
                ROUND(AVG(dns_ms), 1) AS avg_dns,
                ROUND(AVG(connect_ms), 1) AS avg_connect,
                ROUND(AVG(ttfb_ms), 1) AS avg_ttfb,
                SUM(CASE WHEN status_code >= 500 OR status_code = 0 THEN 1 ELSE 0 END) AS error_count,
                MAX(timestamp) AS max_ts
            FROM ping_raw
            WHERE synced_to_notion = 0
            GROUP BY date(timestamp), hour, target
        """).fetchall()
        return [
            {
                "day": r[0], "hour": r[1], "day_of_week": r[2],
                "target": r[3], "sample_count": r[4],
                "avg_total": r[5], "min_total": r[6], "max_total": r[7],
                "avg_dns": r[8], "avg_connect": r[9],
                "avg_ttfb": r[10], "error_count": r[11], "max_ts": r[12],
            }
            for r in rows
        ]

    def mark_synced(self, before_timestamp: str) -> None:
        """Oznacz pomiary starsze lub równe before_timestamp jako zsynchronizowane."""
        self.conn.execute(
            "UPDATE ping_raw SET synced_to_notion = 1 WHERE timestamp <= ? AND synced_to_notion = 0",
            (before_timestamp,),
        )
        self.conn.commit()

    def get_recent(self, n: int = 50) -> list[PingResult]:
        """Ostatnie n pomiarów (dla TUI) — oba targety, najnowsze najpierw."""
        rows = self.conn.execute(
            "SELECT timestamp, target, total_ms, dns_ms, connect_ms, ttfb_ms, "
            "status_code, error, day_of_week, hour "
            "FROM ping_raw ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [
            PingResult(
                timestamp=r[0], target=r[1], total_ms=r[2], dns_ms=r[3],
                connect_ms=r[4], ttfb_ms=r[5], status_code=r[6],
                error=r[7], day_of_week=r[8], hour=r[9],
            )
            for r in rows
        ]

    def get_hourly_summary(self, days: int = 7, target: str = "api") -> list[dict]:
        """Średnie godzinowe z ostatnich N dni (dla TUI)."""
        rows = self.conn.execute("""
            SELECT
                hour,
                ROUND(AVG(total_ms), 1) AS avg_total,
                ROUND(MIN(total_ms), 1) AS min_total,
                ROUND(MAX(total_ms), 1) AS max_total,
                ROUND(AVG(dns_ms), 1) AS avg_dns,
                ROUND(AVG(connect_ms), 1) AS avg_connect,
                ROUND(AVG(ttfb_ms), 1) AS avg_ttfb,
                COUNT(*) AS sample_count,
                SUM(CASE WHEN status_code >= 500 OR status_code = 0 THEN 1 ELSE 0 END) AS error_count
            FROM ping_raw
            WHERE timestamp >= datetime('now', ?) AND target = ?
            GROUP BY hour
            ORDER BY hour
        """, (f"-{days} days", target)).fetchall()
        return [
            {
                "hour": r[0], "avg_total": r[1], "min_total": r[2],
                "max_total": r[3], "avg_dns": r[4], "avg_connect": r[5],
                "avg_ttfb": r[6],
                "sample_count": r[7], "error_count": r[8],
            }
            for r in rows
        ]

    # ── THC: 15-min agregaty ───────────────────────────────────────────────

    def get_15min_unsynced_aggs(self) -> list[dict]:
        """15-minutowe agregaty z niesynchronizowanych pomiarów (dla THC).

        Bucketuje po (day, hour, quarter=floor(minute/15)), target.
        """
        rows = self.conn.execute("""
            SELECT
                date(timestamp) AS day,
                CAST(strftime('%H', timestamp) AS INTEGER) AS hour,
                CAST(strftime('%M', timestamp) AS INTEGER) / 15 AS q,
                day_of_week,
                target,
                COUNT(*) AS sample_count,
                ROUND(AVG(total_ms), 1) AS avg_total,
                ROUND(MIN(total_ms), 1) AS min_total,
                ROUND(MAX(total_ms), 1) AS max_total,
                ROUND(AVG(dns_ms), 1) AS avg_dns,
                ROUND(AVG(connect_ms), 1) AS avg_connect,
                ROUND(AVG(ttfb_ms), 1) AS avg_ttfb,
                SUM(CASE WHEN status_code >= 500 OR status_code = 0 THEN 1 ELSE 0 END) AS error_count,
                MAX(timestamp) AS max_ts
            FROM ping_raw
            WHERE synced_to_thc = 0
            GROUP BY date(timestamp), hour, q, target
            ORDER BY day, hour, q
        """).fetchall()
        return [
            {
                "day": r[0], "hour": r[1], "quarter": r[2],
                "minute": r[2] * 15,
                "day_of_week": r[3], "target": r[4],
                "sample_count": r[5],
                "avg_total": r[6], "min_total": r[7], "max_total": r[8],
                "avg_dns": r[9], "avg_connect": r[10], "avg_ttfb": r[11],
                "error_count": r[12], "max_ts": r[13],
            }
            for r in rows
        ]

    def mark_synced_thc(self, before_timestamp: str) -> None:
        self.conn.execute(
            "UPDATE ping_raw SET synced_to_thc = 1 "
            "WHERE timestamp <= ? AND synced_to_thc = 0",
            (before_timestamp,),
        )
        self.conn.commit()

    # ── THC: metryki dla UI ────────────────────────────────────────────────

    def get_daily_avg(self, target: str = "api") -> dict:
        """Średnia z dzisiejszego dnia UTC (total, ttfb, samples, errors)."""
        row = self.conn.execute("""
            SELECT
                ROUND(AVG(total_ms), 1),
                ROUND(AVG(ttfb_ms), 1),
                ROUND(AVG(dns_ms), 1),
                ROUND(AVG(connect_ms), 1),
                COUNT(*),
                SUM(CASE WHEN status_code >= 500 OR status_code = 0 THEN 1 ELSE 0 END)
            FROM ping_raw
            WHERE date(timestamp) = date('now') AND target = ?
        """, (target,)).fetchone()
        return {
            "avg_total":   row[0] or 0.0,
            "avg_ttfb":    row[1] or 0.0,
            "avg_dns":     row[2] or 0.0,
            "avg_connect": row[3] or 0.0,
            "sample_count": row[4] or 0,
            "error_count":  row[5] or 0,
        }

    def get_rolling_avg_minutes(self, minutes: int = 60, target: str = "api") -> dict:
        """Średnia z ostatnich N minut."""
        row = self.conn.execute("""
            SELECT
                ROUND(AVG(total_ms), 1),
                ROUND(AVG(ttfb_ms), 1),
                ROUND(AVG(dns_ms), 1),
                ROUND(AVG(connect_ms), 1),
                COUNT(*)
            FROM ping_raw
            WHERE timestamp >= datetime('now', ?) AND target = ?
        """, (f"-{minutes} minutes", target)).fetchone()
        return {
            "avg_total":   row[0] or 0.0,
            "avg_ttfb":    row[1] or 0.0,
            "avg_dns":     row[2] or 0.0,
            "avg_connect": row[3] or 0.0,
            "sample_count": row[4] or 0,
        }

    def close(self) -> None:
        self.conn.close()


# ── Pomiar ─────────────────────────────────────────────────────────────────


async def measure_ping(
    target_name: str,
    target_url: str,
) -> PingResult:
    """Pojedynczy ping HEAD z pomiarem składowych (DNS, TCP, TLS, TTFB).

    Tworzy dedykowaną sesję z TraceConfig żeby zmierzyć fazy połączenia.
    """
    now = datetime.now(timezone.utc)
    timings: dict[str, float] = {}

    async def on_dns_start(session, ctx, params):
        timings["dns_start"] = time.perf_counter()

    async def on_dns_end(session, ctx, params):
        timings["dns_end"] = time.perf_counter()

    async def on_connect_start(session, ctx, params):
        timings["connect_start"] = time.perf_counter()

    async def on_connect_end(session, ctx, params):
        timings["connect_end"] = time.perf_counter()

    async def on_request_start(session, ctx, params):
        timings["request_start"] = time.perf_counter()

    async def on_request_end(session, ctx, params):
        timings["request_end"] = time.perf_counter()

    trace = aiohttp.TraceConfig()
    trace.on_dns_resolvehost_start.append(on_dns_start)
    trace.on_dns_resolvehost_end.append(on_dns_end)
    trace.on_connection_create_start.append(on_connect_start)
    trace.on_connection_create_end.append(on_connect_end)
    trace.on_request_start.append(on_request_start)
    trace.on_request_end.append(on_request_end)

    t0 = time.perf_counter()
    try:
        # Nowa sesja za każdym razem — bez connection poolingu,
        # żeby mierzyć pełny cykl DNS→TCP→TLS→TTFB
        async with aiohttp.ClientSession(trace_configs=[trace]) as http:
            async with http.head(
                target_url,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as r:
                t1 = time.perf_counter()

                total_ms = round((t1 - t0) * 1000, 1)

                # DNS lookup
                dns_ms = round(
                    (timings.get("dns_end", 0) - timings.get("dns_start", 0)) * 1000, 1
                ) if "dns_start" in timings else 0.0

                # TCP + TLS connect
                connect_ms = round(
                    (timings.get("connect_end", 0) - timings.get("connect_start", 0)) * 1000, 1
                ) if "connect_start" in timings else 0.0

                # TTFB — czas serwera (request wysłany → odpowiedź)
                ttfb_ms = round(
                    (timings.get("request_end", 0) - timings.get("request_start", 0)) * 1000, 1
                ) if "request_start" in timings and "request_end" in timings else 0.0

                # Korekta ujemnych (mogą powstać przy redirectach)
                dns_ms = max(dns_ms, 0.0)
                connect_ms = max(connect_ms, 0.0)
                ttfb_ms = max(ttfb_ms, 0.0)

                server_ok = r.status < 500
                return PingResult(
                    timestamp=now.isoformat(),
                    target=target_name,
                    total_ms=total_ms,
                    dns_ms=dns_ms,
                    connect_ms=connect_ms,
                    ttfb_ms=ttfb_ms,
                    status_code=r.status,
                    error=None if server_ok else f"HTTP {r.status}",
                    day_of_week=now.weekday(),
                    hour=now.hour,
                )
    except Exception as exc:
        t1 = time.perf_counter()
        return PingResult(
            timestamp=now.isoformat(),
            target=target_name,
            total_ms=round((t1 - t0) * 1000, 1),
            dns_ms=0.0, connect_ms=0.0, ttfb_ms=0.0,
            status_code=0,
            error=str(exc)[:500],
            day_of_week=now.weekday(),
            hour=now.hour,
        )


# ── Notion sync ────────────────────────────────────────────────────────────


def _build_ping_properties(agg: dict, title_prop: str = "Hour Slot") -> dict:
    """Buduj Notion properties dla hourly aggregatu."""
    day_name = DAY_NAMES[agg["day_of_week"]] if 0 <= agg["day_of_week"] <= 6 else "?"
    title = f"{agg['day']} {agg['hour']:02d}:00 UTC ({day_name[:3]}) [{agg['target']}]"

    return {
        title_prop: {"title": [{"text": {"content": title}}]},
        "Date":           {"date": {"start": agg["day"]}},
        "Hour":           {"number": agg["hour"]},
        "Day of Week":    {"select": {"name": day_name}},
        "Target":         {"select": {"name": agg["target"]}},
        "Avg Total ms":   {"number": agg["avg_total"]},
        "Min Total ms":   {"number": agg["min_total"]},
        "Max Total ms":   {"number": agg["max_total"]},
        "Avg DNS ms":     {"number": agg["avg_dns"]},
        "Avg Connect ms": {"number": agg["avg_connect"]},
        "Avg TTFB ms":    {"number": agg["avg_ttfb"]},
        "Sample Count":   {"number": agg["sample_count"]},
        "Error Count":    {"number": agg["error_count"]},
    }


async def _sync_to_notion(
    state: PingState,
    http: aiohttp.ClientSession,
    cfg: PingConfig,
) -> tuple[int, int]:
    """Push niesynchronizowanych hourly agregatów do Notion."""
    assert cfg.notion_token and cfg.ping_db_id

    headers = {
        "Authorization": f"Bearer {cfg.notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    aggs = state.get_unsynced_hourly_aggs()
    if not aggs:
        return 0, 0

    created = 0
    failed = 0
    max_ts = ""

    for agg in aggs:
        props = _build_ping_properties(agg)
        payload = {
            "parent": {"database_id": cfg.ping_db_id},
            "properties": props,
        }
        async with http.post(
            f"{NOTION_API}/pages", headers=headers, json=payload,
        ) as r:
            if r.status == 200:
                created += 1
                if agg["max_ts"] > max_ts:
                    max_ts = agg["max_ts"]
                log.info(
                    "Notion: %s %02d:00 — avg %.0fms (%d samples)",
                    agg["day"], agg["hour"], agg["avg_total"], agg["sample_count"],
                )
            else:
                failed += 1
                log.error(
                    "Notion błąd: %s %02d:00 — %d %s",
                    agg["day"], agg["hour"], r.status, (await r.text())[:200],
                )

    if max_ts and created > 0:
        state.mark_synced(max_ts)

    return created, failed


# ── THC Notion sync (15-min buckets) ───────────────────────────────────────


def _build_thc_properties(agg: dict) -> dict:
    """Notion properties dla 15-min agregatu THC."""
    from tost.thc_tiers import get_tier
    from datetime import datetime as _dt, timezone as _tz

    day_name = DAY_NAMES[agg["day_of_week"]] if 0 <= agg["day_of_week"] <= 6 else "?"
    # Bucket start w UTC — do wyliczenia tieru
    bucket_dt = _dt.fromisoformat(f"{agg['day']}T{agg['hour']:02d}:{agg['minute']:02d}:00+00:00")
    tier = get_tier(bucket_dt).value

    title = (
        f"{agg['day']} {agg['hour']:02d}:{agg['minute']:02d} UTC "
        f"({day_name[:3]}) [{agg['target']}]"
    )
    return {
        "Slot":           {"title": [{"text": {"content": title}}]},
        "Date":           {"date": {"start": agg["day"]}},
        "Hour":           {"number": agg["hour"]},
        "Minute":         {"number": agg["minute"]},
        "Day of Week":    {"select": {"name": day_name}},
        "Target":         {"select": {"name": agg["target"]}},
        "Tier":           {"select": {"name": tier}},
        "Avg Total ms":   {"number": agg["avg_total"]},
        "Min Total ms":   {"number": agg["min_total"]},
        "Max Total ms":   {"number": agg["max_total"]},
        "Avg DNS ms":     {"number": agg["avg_dns"]},
        "Avg Connect ms": {"number": agg["avg_connect"]},
        "Avg TTFB ms":    {"number": agg["avg_ttfb"]},
        "Sample Count":   {"number": agg["sample_count"]},
        "Error Count":    {"number": agg["error_count"]},
    }


async def _sync_to_thc(
    state: PingState,
    http: aiohttp.ClientSession,
    cfg: PingConfig,
) -> tuple[int, int]:
    """Push niesynchronizowanych 15-min agregatów do bazy THC."""
    assert cfg.notion_token and cfg.thc_db_id

    headers = {
        "Authorization": f"Bearer {cfg.notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    aggs = state.get_15min_unsynced_aggs()
    if not aggs:
        return 0, 0

    created = 0
    failed = 0
    max_ts = ""

    for agg in aggs:
        payload = {
            "parent": {"database_id": cfg.thc_db_id},
            "properties": _build_thc_properties(agg),
        }
        async with http.post(
            f"{NOTION_API}/pages", headers=headers, json=payload,
        ) as r:
            if r.status == 200:
                created += 1
                if agg["max_ts"] > max_ts:
                    max_ts = agg["max_ts"]
                log.info(
                    "THC: %s %02d:%02d [%s] — avg %.0fms (%d samples)",
                    agg["day"], agg["hour"], agg["minute"], agg["target"],
                    agg["avg_total"], agg["sample_count"],
                )
            else:
                failed += 1
                log.error(
                    "THC błąd: %s %02d:%02d — %d %s",
                    agg["day"], agg["hour"], agg["minute"],
                    r.status, (await r.text())[:200],
                )

    if max_ts and created > 0:
        state.mark_synced_thc(max_ts)

    return created, failed


# ── Główna pętla ───────────────────────────────────────────────────────────


async def run_ping_loop(
    cfg: PingConfig,
    state_db: str | Path = DEFAULT_PING_DB,
    once: bool = False,
) -> None:
    """Pętla: ping co interval, sync Notion (hourly) + THC (15-min)."""
    state = PingState(state_db)
    last_notion_sync = 0.0
    last_thc_sync = 0.0

    while True:
        # Pinguj wszystkie targety równolegle (każdy tworzy własną sesję)
        tasks = [
            measure_ping(name, url)
            for name, url in PING_TARGETS
        ]
        results = await asyncio.gather(*tasks)

        for result in results:
            state.insert_result(result)
            if result.error:
                log.warning(
                    "[%s] Total: %.0fms | DNS: %.0f Connect: %.0f TTFB: %.0f (error=%s)",
                    result.target, result.total_ms, result.dns_ms,
                    result.connect_ms, result.ttfb_ms, result.error,
                )
            else:
                log.info(
                    "[%s] Total: %.0fms | DNS: %.0f Connect: %.0f TTFB: %.0fms",
                    result.target, result.total_ms, result.dns_ms,
                    result.connect_ms, result.ttfb_ms,
                )

        # Sonar — jeden pip na cykl (nie dwa z api+status). Tylko gdy główny
        # target (api) odpowiedział bez błędu; inaczej cisza.
        api_result = next((r for r in results if r.target == "api"), None)
        if api_result and not api_result.error:
            try:
                from tost.sound import play_sonar
                play_sonar()
            except Exception as e:  # noqa: BLE001 — dźwięk nie może przerwać pętli
                log.debug("Sonar error: %s", e)

        # Notion sync — hourly aggs (stara baza)
        now = time.time()
        if (
            cfg.notion_token
            and cfg.ping_db_id
            and now - last_notion_sync >= cfg.notion_sync_interval
        ):
            async with aiohttp.ClientSession() as http:
                created, failed_count = await _sync_to_notion(state, http, cfg)
            last_notion_sync = now
            if created or failed_count:
                log.info("Notion sync: %d created, %d failed", created, failed_count)

        # THC sync — 15-min buckets (nowa baza)
        if (
            cfg.notion_token
            and cfg.thc_db_id
            and now - last_thc_sync >= cfg.thc_sync_interval
        ):
            async with aiohttp.ClientSession() as http:
                created, failed_count = await _sync_to_thc(state, http, cfg)
            last_thc_sync = now
            if created or failed_count:
                log.info("THC sync: %d created, %d failed", created, failed_count)

        if once:
            break

        await asyncio.sleep(cfg.ping_interval)

    state.close()
