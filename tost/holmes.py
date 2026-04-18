"""Holmes — analizator anomalii zużycia tokenów w sesjach Claude Code.

Wykrywa podejrzane wzorce i zapisuje je do bazy Notion "Suspects".

Reguły konfigurowane w holmes_rules.toml (obok tego pliku).
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from tost.jsonl_scanner import SessionAggregate, scan_all_sessions
from tost.cost import format_cost

log = logging.getLogger("tost.holmes")

RULES_FILE = Path(__file__).parent / "holmes_rules.toml"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


# ── Wynik analizy ────────────────────────────────────────────────────────────


@dataclass
class Suspect:
    session: SessionAggregate
    rule_name: str
    category: str
    severity: str
    description: str
    detail: str          # konkretne liczby / powód flagowania
    triggered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Ładowanie reguł ──────────────────────────────────────────────────────────


def _load_rules() -> dict[str, Any]:
    """Wczytaj holmes_rules.toml. Fallback na wbudowane defaults jeśli brak pliku."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            log.warning("tomllib/tomli niedostępne — używam domyślnych reguł")
            return _default_rules()

    if not RULES_FILE.exists():
        log.warning("holmes_rules.toml nie znaleziony — używam domyślnych reguł")
        return _default_rules()

    with open(RULES_FILE, "rb") as f:
        data = tomllib.load(f)
    return data.get("rules", {})


def _default_rules() -> dict[str, Any]:
    return {
        "cache_invalidation": {
            "enabled": True, "min_messages": 10, "max_cache_read_ratio": 0.05,
            "min_input_tokens": 50000,
            "category": "Cache Invalidation Bug", "severity": "HIGH",
            "description": "Duże sesje bez cache",
        },
        "long_session_overflow": {
            "enabled": True, "min_messages": 40, "min_total_tokens": 100000,
            "category": "Long Session Overflow", "severity": "MEDIUM",
            "description": "Długa sesja bez resetu",
        },
        "think_mode_waste": {
            "enabled": True, "min_output_to_input_ratio": 0.8, "min_output_tokens": 10000,
            "min_messages": 5,
            "category": "Think Mode / Output Waste", "severity": "MEDIUM",
            "description": "Wysoka proporcja output/input",
        },
        "mcp_overload": {
            "enabled": True, "min_cost_usd": 1.0, "max_messages": 20,
            "category": "MCP/Plugin Overload", "severity": "HIGH",
            "description": "Wysoki koszt przy małej liczbie wiadomości",
        },
        "session_cost_spike": {
            "enabled": True, "spike_multiplier": 5.0, "min_cost_usd": 0.50,
            "category": "Cost Spike", "severity": "HIGH",
            "description": "Koszt sesji wielokrotnie przekracza medianę",
        },
        "high_cache_creation": {
            "enabled": True, "min_cache_creation_tokens": 30000,
            "max_cache_read_to_creation_ratio": 0.10, "min_messages": 5,
            "category": "Wasted Cache Creation", "severity": "LOW",
            "description": "Dużo cache creation bez odczytów",
        },
    }


# ── Silnik reguł ─────────────────────────────────────────────────────────────


def _parse_date_filter(date_from: str | None, date_to: str | None):
    """Zwróć parę (dt_from, dt_to) jako datetime UTC lub (None, None)."""
    fmt = "%Y-%m-%d"
    dt_from = datetime.strptime(date_from, fmt).replace(tzinfo=timezone.utc) if date_from else None
    dt_to = datetime.strptime(date_to, fmt).replace(tzinfo=timezone.utc) if date_to else None
    return dt_from, dt_to


def _session_in_range(s: SessionAggregate, dt_from, dt_to) -> bool:
    if not s.last_message_at:
        return False
    try:
        ts = datetime.fromisoformat(s.last_message_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt_from and ts < dt_from:
        return False
    if dt_to and ts > dt_to:
        return False
    return True


def run_holmes(
    sessions: list[SessionAggregate],
    rules: dict[str, Any],
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Suspect]:
    """Uruchom wszystkie reguły na liście sesji. Zwróć listę podejrzanych."""

    dt_from, dt_to = _parse_date_filter(date_from, date_to)
    filtered = [s for s in sessions if _session_in_range(s, dt_from, dt_to)]
    log.info("Holmes: %d sesji w zakresie dat (z %d łącznie)", len(filtered), len(sessions))

    suspects: list[Suspect] = []

    # Mediana kosztów (do reguły spike)
    costs = [s.cost_usd for s in filtered if s.cost_usd > 0]
    median_cost = statistics.median(costs) if len(costs) >= 3 else None

    for s in filtered:
        suspects.extend(_check_session(s, rules, median_cost))

    return suspects


def _check_session(
    s: SessionAggregate,
    rules: dict[str, Any],
    median_cost: float | None,
) -> list[Suspect]:
    found: list[Suspect] = []

    def _suspect(rule_name: str, detail: str) -> Suspect:
        r = rules[rule_name]
        return Suspect(
            session=s,
            rule_name=rule_name,
            category=r["category"],
            severity=r["severity"],
            description=r["description"],
            detail=detail,
        )

    # ── Cache Invalidation ──
    r = rules.get("cache_invalidation", {})
    if r.get("enabled"):
        total_input = s.input_tokens + s.cache_read_tokens + s.cache_creation_tokens
        cache_ratio = s.cache_read_tokens / total_input if total_input > 0 else 0.0
        if (
            s.message_count >= r.get("min_messages", 10)
            and s.input_tokens >= r.get("min_input_tokens", 50_000)
            and cache_ratio < r.get("max_cache_read_ratio", 0.05)
        ):
            found.append(_suspect(
                "cache_invalidation",
                f"cache_read_ratio={cache_ratio:.1%}, input={s.input_tokens:,}, msgs={s.message_count}",
            ))

    # ── Long Session Overflow ──
    r = rules.get("long_session_overflow", {})
    if r.get("enabled"):
        if (
            s.message_count >= r.get("min_messages", 40)
            and s.total_tokens >= r.get("min_total_tokens", 100_000)
        ):
            found.append(_suspect(
                "long_session_overflow",
                f"msgs={s.message_count}, total_tokens={s.total_tokens:,}",
            ))

    # ── Think Mode Waste ──
    r = rules.get("think_mode_waste", {})
    if r.get("enabled"):
        ratio = s.output_tokens / s.input_tokens if s.input_tokens > 0 else 0.0
        if (
            s.message_count >= r.get("min_messages", 5)
            and s.output_tokens >= r.get("min_output_tokens", 10_000)
            and ratio >= r.get("min_output_to_input_ratio", 0.8)
        ):
            found.append(_suspect(
                "think_mode_waste",
                f"out/in ratio={ratio:.2f}, output={s.output_tokens:,}, input={s.input_tokens:,}",
            ))

    # ── MCP/Plugin Overload ──
    r = rules.get("mcp_overload", {})
    if r.get("enabled"):
        if (
            s.cost_usd >= r.get("min_cost_usd", 1.0)
            and s.message_count <= r.get("max_messages", 20)
        ):
            found.append(_suspect(
                "mcp_overload",
                f"cost={format_cost(s.cost_usd)}, msgs={s.message_count}",
            ))

    # ── Cost Spike ──
    r = rules.get("session_cost_spike", {})
    if r.get("enabled") and median_cost is not None and median_cost > 0:
        threshold = median_cost * r.get("spike_multiplier", 5.0)
        if (
            s.cost_usd >= r.get("min_cost_usd", 0.50)
            and s.cost_usd >= threshold
        ):
            found.append(_suspect(
                "session_cost_spike",
                f"cost={format_cost(s.cost_usd)}, median={format_cost(median_cost)}, "
                f"ratio={s.cost_usd / median_cost:.1f}x",
            ))

    # ── Wasted Cache Creation ──
    r = rules.get("high_cache_creation", {})
    if r.get("enabled"):
        read_to_creation = (
            s.cache_read_tokens / s.cache_creation_tokens
            if s.cache_creation_tokens > 0 else 0.0
        )
        if (
            s.message_count >= r.get("min_messages", 5)
            and s.cache_creation_tokens >= r.get("min_cache_creation_tokens", 30_000)
            and read_to_creation < r.get("max_cache_read_to_creation_ratio", 0.10)
        ):
            found.append(_suspect(
                "high_cache_creation",
                f"cache_create={s.cache_creation_tokens:,}, cache_read={s.cache_read_tokens:,}, "
                f"read/create={read_to_creation:.1%}",
            ))

    return found


# ── Notion — baza Suspects ───────────────────────────────────────────────────


def _build_suspect_properties(suspect: Suspect, title_prop: str = "Session") -> dict:
    s = suspect.session
    project_short = s.project.rstrip("/").rsplit("/", 1)[-1] or s.project
    title = f"[{suspect.severity}] {project_short} · {s.session_id[:8]}"

    return {
        title_prop: {"title": [{"text": {"content": title[:200]}}]},
        "Session ID":  {"rich_text": [{"text": {"content": s.session_id}}]},
        "Project":     {"rich_text": [{"text": {"content": s.project[:1900]}}]},
        "Rule":        {"rich_text": [{"text": {"content": suspect.rule_name}}]},
        "Category":    {"select":    {"name": suspect.category[:100]}},
        "Severity":    {"select":    {"name": suspect.severity}},
        "Description": {"rich_text": [{"text": {"content": suspect.description[:1900]}}]},
        "Detail":      {"rich_text": [{"text": {"content": suspect.detail[:1900]}}]},
        "Model":       {"select":    {"name": s.primary_model[:100]}},
        "Messages":    {"number": s.message_count},
        "Input tokens": {"number": s.input_tokens},
        "Output tokens": {"number": s.output_tokens},
        "Cache read":  {"number": s.cache_read_tokens},
        "Cache create": {"number": s.cache_creation_tokens},
        "Cost USD":    {"number": round(s.cost_usd, 6)},
        "Detected at": {"date": {"start": suspect.triggered_at}},
        **({"Session start": {"date": {"start": s.started_at}}} if s.started_at else {}),
        **({"Session end":   {"date": {"start": s.last_message_at}}} if s.last_message_at else {}),
    }


async def _ensure_suspects_db(
    http: aiohttp.ClientSession,
    headers: dict,
    parent_page_id: str,
    title_prop: str = "Session",
) -> str:
    """Utwórz bazę Suspects w Notion jeśli nie istnieje. Zwróć database_id."""
    url = f"{NOTION_API}/databases"
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "TOST Suspects"}}],
        "properties": {
            title_prop:       {"title": {}},
            "Session ID":     {"rich_text": {}},
            "Project":        {"rich_text": {}},
            "Rule":           {"rich_text": {}},
            "Category":       {"select": {}},
            "Severity":       {"select": {}},
            "Description":    {"rich_text": {}},
            "Detail":         {"rich_text": {}},
            "Model":          {"select": {}},
            "Messages":       {"number": {}},
            "Input tokens":   {"number": {}},
            "Output tokens":  {"number": {}},
            "Cache read":     {"number": {}},
            "Cache create":   {"number": {}},
            "Cost USD":       {"number": {"format": "dollar"}},
            "Detected at":    {"date": {}},
            "Session start":  {"date": {}},
            "Session end":    {"date": {}},
        },
    }
    async with http.post(url, headers=headers, json=payload) as r:
        if r.status != 200:
            body = await r.text()
            raise RuntimeError(f"Nie można utworzyć bazy Suspects: {r.status} {body[:300]}")
        data = await r.json()
        return data["id"]


async def push_suspects_to_notion(
    suspects: list[Suspect],
    notion_token: str,
    suspects_db_id: str,
    title_prop: str = "Session",
) -> tuple[int, int]:
    """Zapisz suspects do Notion. Zwróć (created, failed)."""
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    created = 0
    failed = 0

    async with aiohttp.ClientSession() as http:
        for suspect in suspects:
            props = _build_suspect_properties(suspect, title_prop)
            payload = {
                "parent": {"database_id": suspects_db_id},
                "properties": props,
            }
            url = f"{NOTION_API}/pages"
            async with http.post(url, headers=headers, json=payload) as r:
                if r.status == 200:
                    created += 1
                    log.info(
                        "Suspect zapisany: [%s] %s — %s",
                        suspect.severity, suspect.session.session_id[:8], suspect.category,
                    )
                else:
                    failed += 1
                    log.error(
                        "Błąd zapisu suspect %s: %d %s",
                        suspect.session.session_id[:8], r.status, (await r.text())[:200],
                    )

    return created, failed


# ── Publiczne API ────────────────────────────────────────────────────────────


def analyze_and_push(
    date_from: str | None,
    date_to: str | None,
    notion_token: str,
    suspects_db_id: str,
) -> tuple[list[Suspect], int, int]:
    """Synchroniczny wrapper dla CLI: skanuj, wykryj, wypchnij do Notion."""
    rules = _load_rules()
    sessions = list(scan_all_sessions())
    suspects = run_holmes(sessions, rules, date_from, date_to)
    if not suspects:
        return suspects, 0, 0
    created, failed = asyncio.run(
        push_suspects_to_notion(suspects, notion_token, suspects_db_id)
    )
    return suspects, created, failed
