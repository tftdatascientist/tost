"""Taryfa — synchronizacja do Notion.

Jedna strona Notion = jeden kubełek godzinowy (date × hour UTC). Upsert po
(date, hour) — state mapping w `tost_taryfa.db` (tabela taryfa_notion_pages).

Auto-create bazy: jeśli `TARYFA_NOTION_DB_ID` nie ustawione, a mamy
`TARYFA_NOTION_PARENT_PAGE_ID`, tworzymy bazę pod parent page i cache'ujemy
database_id w taryfa_config (żeby przy restarcie nie tworzyć drugiej).

Schemat bazy (wszystkie pola case-sensitive):
    Slot              (title)
    Date              (date)
    Hour              (number, 0-23)
    Tokens            (number)
    Cost USD          (number, dollar)
    Baseline median   (number)
    Baseline p90      (number)
    Baseline samples  (number)
    Burn ratio        (number)
    Z-score           (number)
    Tariff            (select: ZIELONA/ZOLTA/POMARANCZOWA/CZERWONA + kolory)
    Server tier       (select: GREEN/YELLOW/ORANGE/RED)
    Synced at         (date)
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone

import aiohttp

from tost.taryfa import (
    HourlyBucket,
    Taryfa,
    TARYFA_LABELS,
    TARYFA_NOTION_COLORS,
    TaryfaState,
    _SEVERITY,
    _mad,
    _percentile,
    _tariff_from_ratio,
    _tariff_from_z,
    load_thresholds,
)
from tost.thc_tiers import Tier, get_tier

log = logging.getLogger("tost.taryfa_notion")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Klucz do cache'u w taryfa_config
CACHED_DB_ID_KEY = "notion_database_id"

# Kolory Notion dla server-tier select (z thc_tiers)
TIER_NOTION_COLORS: dict[Tier, str] = {
    Tier.GREEN:  "green",
    Tier.YELLOW: "yellow",
    Tier.ORANGE: "orange",
    Tier.RED:    "red",
}


# ── Auto-create bazy ───────────────────────────────────────────────────────


async def _ensure_taryfa_db(
    http: aiohttp.ClientSession,
    headers: dict,
    parent_page_id: str,
) -> str:
    """Utwórz bazę Taryfa pod parent_page_id. Zwróć database_id."""
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "TOST Taryfa"}}],
        "properties": {
            "Slot":             {"title": {}},
            "Date":             {"date": {}},
            "Hour":             {"number": {}},
            "Tokens":           {"number": {}},
            "Cost USD":         {"number": {"format": "dollar"}},
            "Baseline median":  {"number": {}},
            "Baseline p90":     {"number": {}},
            "Baseline samples": {"number": {}},
            "Burn ratio":       {"number": {}},
            "Z-score":          {"number": {}},
            "Tariff": {
                "select": {
                    "options": [
                        {"name": TARYFA_LABELS[t], "color": TARYFA_NOTION_COLORS[t]}
                        for t in (Taryfa.GREEN, Taryfa.YELLOW, Taryfa.ORANGE, Taryfa.RED)
                    ],
                },
            },
            "Server tier": {
                "select": {
                    "options": [
                        {"name": t.value, "color": TIER_NOTION_COLORS[t]}
                        for t in (Tier.GREEN, Tier.YELLOW, Tier.ORANGE, Tier.RED)
                    ],
                },
            },
            "Synced at":        {"date": {}},
        },
    }
    async with http.post(
        f"{NOTION_API}/databases", headers=headers, json=payload,
    ) as r:
        if r.status != 200:
            body = await r.text()
            raise RuntimeError(
                f"Taryfa: nie mozna utworzyc bazy Notion: {r.status} {body[:300]}"
            )
        data = await r.json()
        return data["id"]


async def resolve_taryfa_db_id(
    http: aiohttp.ClientSession,
    headers: dict,
    state: TaryfaState,
    explicit_db_id: str | None,
    parent_page_id: str | None,
) -> str | None:
    """Zwróć database_id lub None jeśli nic nie mamy.

    Priorytet:
        1. explicit_db_id (env `TARYFA_NOTION_DB_ID`)
        2. cached (state.taryfa_config[notion_database_id])
        3. auto-create pod parent_page_id → cache → zwróć
        4. None (brak konfiguracji)
    """
    if explicit_db_id:
        return explicit_db_id
    cached = state.get_config(CACHED_DB_ID_KEY)
    if cached:
        return cached
    if parent_page_id:
        try:
            db_id = await _ensure_taryfa_db(http, headers, parent_page_id)
        except RuntimeError as e:
            log.error("Taryfa: %s", e)
            return None
        state.set_config(CACHED_DB_ID_KEY, db_id)
        log.info("Taryfa: utworzono baze Notion %s pod parent %s", db_id, parent_page_id)
        return db_id
    return None


# ── Budowanie properties ──────────────────────────────────────────────────


def _bucket_to_properties(
    bucket: HourlyBucket,
    baseline_median: float,
    baseline_p90: float,
    baseline_samples: int,
    ratio: float,
    z_score: float,
    tariff: Taryfa,
    server_tier: Tier,
    synced_iso: str,
) -> dict:
    title = f"{bucket.date} {bucket.hour:02d}:00 UTC"
    return {
        "Slot":             {"title": [{"text": {"content": title}}]},
        "Date":             {"date": {"start": bucket.date}},
        "Hour":             {"number": bucket.hour},
        "Tokens":           {"number": bucket.total_tokens},
        "Cost USD":         {"number": round(bucket.cost_usd, 6)},
        "Baseline median":  {"number": round(baseline_median, 1)},
        "Baseline p90":     {"number": round(baseline_p90, 1)},
        "Baseline samples": {"number": baseline_samples},
        "Burn ratio":       {"number": round(ratio, 3)},
        "Z-score":          {"number": round(z_score, 3)},
        "Tariff":           {"select": {"name": TARYFA_LABELS[tariff]}},
        "Server tier":      {"select": {"name": server_tier.value}},
        "Synced at":        {"date": {"start": synced_iso}},
    }


# ── Upsert ────────────────────────────────────────────────────────────────


async def _create_page(
    http: aiohttp.ClientSession,
    headers: dict,
    database_id: str,
    properties: dict,
) -> str | None:
    payload = {"parent": {"database_id": database_id}, "properties": properties}
    async with http.post(
        f"{NOTION_API}/pages", headers=headers, json=payload,
    ) as r:
        if r.status != 200:
            log.error(
                "Taryfa create failed: %d %s", r.status, (await r.text())[:300],
            )
            return None
        data = await r.json()
        return data.get("id")


async def _update_page(
    http: aiohttp.ClientSession,
    headers: dict,
    page_id: str,
    properties: dict,
) -> bool:
    async with http.patch(
        f"{NOTION_API}/pages/{page_id}", headers=headers, json={"properties": properties},
    ) as r:
        if r.status == 200:
            return True
        log.error(
            "Taryfa update failed (%s): %d %s", page_id, r.status, (await r.text())[:300],
        )
        # False — caller próbuje create'a jako fallback
        return False


def _recompute_metrics_for_bucket(
    state: TaryfaState, bucket: HourlyBucket,
) -> tuple[float, float, int, float, float, Taryfa, Tier]:
    """Policz metryki taryfy dla *tego konkretnego* kubełka (nie bieżącego).

    Dla kubełków z przeszłości: `elapsed_fraction = 1.0`, więc ratio = total/median.
    """
    bucket_dt = datetime.fromisoformat(
        f"{bucket.date}T{bucket.hour:02d}:59:59+00:00"
    )
    thr = load_thresholds()
    days = int(thr.get("baseline_days", 7))
    min_samples = int(thr.get("min_samples", 5))

    baseline = state.get_baseline_for_hour(bucket.hour, days, bucket.date)
    if len(baseline) < min_samples:
        baseline = state.get_baseline_all_hours(days, bucket.date)

    if len(baseline) < min_samples:
        return (0.0, 0.0, len(baseline), 0.0, 0.0, Taryfa.GREEN, get_tier(bucket_dt))

    sorted_b = sorted(baseline)
    median = float(statistics.median(sorted_b))
    mad = _mad(sorted_b, median)
    mad_scaled = 1.4826 * mad if mad > 0 else max(median * 0.1, 1.0)
    p90 = _percentile(sorted_b, 0.90)

    total = bucket.total_tokens
    ratio = total / median if median > 0 else 0.0
    z = (total - median) / mad_scaled if mad_scaled > 0 else 0.0
    t_ratio = _tariff_from_ratio(ratio, total, p90, thr)
    t_z = _tariff_from_z(z, thr)
    taryfa = max([t_ratio, t_z], key=lambda t: _SEVERITY[t])
    server_tier = get_tier(bucket_dt)
    return (median, p90, len(baseline), ratio, z, taryfa, server_tier)


async def sync_taryfa_to_notion(
    state: TaryfaState,
    notion_token: str,
    database_id: str,
    lookback_days: int = 2,
) -> tuple[int, int, int]:
    """Push kubełków z ostatnich `lookback_days` do Notion (upsert).

    Returns: (created, updated, failed)
    """
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    # lookback_days dni wstecz od północy UTC
    cutoff_dt = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ) - timedelta(days=lookback_days)

    rows = state.conn.execute(
        """
        SELECT date, hour, input_tokens, output_tokens,
               cache_read_tokens, cache_creation_tokens,
               cost_usd, message_count
        FROM taryfa_hourly
        WHERE date >= ?
        ORDER BY date, hour
        """,
        (cutoff_dt.strftime("%Y-%m-%d"),),
    ).fetchall()

    buckets: list[HourlyBucket] = [
        HourlyBucket(
            date=r[0], hour=r[1],
            input_tokens=r[2], output_tokens=r[3],
            cache_read_tokens=r[4], cache_creation_tokens=r[5],
            cost_usd=r[6], message_count=r[7],
        )
        for r in rows
    ]

    if not buckets:
        return (0, 0, 0)

    created = 0
    updated = 0
    failed = 0
    synced_iso = datetime.now(timezone.utc).isoformat()

    async with aiohttp.ClientSession() as http:
        for bucket in buckets:
            total = bucket.total_tokens
            if total == 0:
                continue

            # Skip jeśli bez zmian od ostatniego syncu
            existing = state.get_notion_page(bucket.date, bucket.hour)
            if existing and existing[1] == total:
                continue

            median, p90, samples, ratio, z, tariff, server_tier = _recompute_metrics_for_bucket(
                state, bucket,
            )
            props = _bucket_to_properties(
                bucket=bucket,
                baseline_median=median,
                baseline_p90=p90,
                baseline_samples=samples,
                ratio=ratio, z_score=z,
                tariff=tariff, server_tier=server_tier,
                synced_iso=synced_iso,
            )

            if existing:
                page_id, _ = existing
                ok = await _update_page(http, headers, page_id, props)
                if ok:
                    updated += 1
                    state.set_notion_page(bucket.date, bucket.hour, page_id, total, synced_iso)
                else:
                    # Możliwe że page zarchiwizowana — utwórz na nowo
                    new_id = await _create_page(http, headers, database_id, props)
                    if new_id:
                        created += 1
                        state.set_notion_page(bucket.date, bucket.hour, new_id, total, synced_iso)
                    else:
                        failed += 1
            else:
                new_id = await _create_page(http, headers, database_id, props)
                if new_id:
                    created += 1
                    state.set_notion_page(bucket.date, bucket.hour, new_id, total, synced_iso)
                else:
                    failed += 1

    state.commit()
    return (created, updated, failed)
