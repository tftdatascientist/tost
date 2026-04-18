"""Notion sync — push Claude Code session usage to a Notion database every N seconds.

Usage:
    export NOTION_TOKEN=secret_xxx
    export NOTION_DATABASE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    python -m tost.notion_sync

Or after wiring into cli.py:
    tost sync

The sync writes ONE Notion page per session and updates it in place as the
session grows. State (file mtimes + session→page mapping) is persisted to
~/.claude/tost_notion.db so the loop is restart-safe and idempotent.

Required Notion database properties (case-sensitive):
    - Session       (title)            ← title property, name configurable
    - Session ID    (rich_text)        ← used as the upsert key
    - Project       (rich_text)
    - Model         (select)
    - Started       (date)
    - Last message  (date)
    - Messages      (number)
    - Input tokens  (number)
    - Output tokens (number)
    - Cache read    (number)
    - Cache create  (number)
    - Cost USD      (number)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from tost.jsonl_scanner import SessionAggregate, get_changed_sessions

log = logging.getLogger("tost.notion_sync")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

DEFAULT_STATE_DB = Path.home() / ".claude" / "tost_notion.db"


# ── Config & state ──────────────────────────────────────────────────────────


@dataclass
class NotionConfig:
    token: str
    database_id: str
    interval: float = 60.0
    title_property: str = "Session"
    # Taryfa — opcjonalne; jeśli parent_page_id podany, baza auto-tworzona
    taryfa_db_id: str | None = None
    taryfa_parent_page_id: str | None = None
    taryfa_sync_interval: float = 900.0  # 15 min


class NotionSyncState:
    """Persists file mtimes and session→page_id mapping in SQLite."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS notion_file_mtimes (
        file_path TEXT PRIMARY KEY,
        mtime REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notion_pages (
        session_id TEXT PRIMARY KEY,
        page_id TEXT NOT NULL,
        last_synced REAL NOT NULL DEFAULT 0
    );
    """

    def __init__(self, db_path: str | Path) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def get_mtimes(self) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT file_path, mtime FROM notion_file_mtimes"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def set_mtime(self, file_path: str, mtime: float) -> None:
        self.conn.execute(
            "INSERT INTO notion_file_mtimes(file_path, mtime) VALUES(?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET mtime=excluded.mtime",
            (file_path, mtime),
        )
        self.conn.commit()

    def get_page_id(self, session_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT page_id FROM notion_pages WHERE session_id=?", (session_id,)
        ).fetchone()
        return row[0] if row else None

    def set_page_id(self, session_id: str, page_id: str, ts: float) -> None:
        self.conn.execute(
            "INSERT INTO notion_pages(session_id, page_id, last_synced) "
            "VALUES(?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "page_id=excluded.page_id, last_synced=excluded.last_synced",
            (session_id, page_id, ts),
        )
        self.conn.commit()

    def has_any_pages(self) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM notion_pages LIMIT 1"
        ).fetchone() is not None

    def close(self) -> None:
        self.conn.close()


# ── Notion property builder ─────────────────────────────────────────────────


def _build_properties(agg: SessionAggregate, title_prop: str) -> dict:
    """Build Notion page properties payload for an aggregate."""
    project_short = agg.project.rstrip("/").rsplit("/", 1)[-1] or agg.project
    title = f"{project_short} · {agg.session_id[:8]}"

    props: dict = {
        title_prop: {
            "title": [{"text": {"content": title[:200]}}]
        },
        "Session ID": {
            "rich_text": [{"text": {"content": agg.session_id}}]
        },
        "Project": {
            "rich_text": [{"text": {"content": agg.project[:1900]}}]
        },
        "Model": {
            "select": {"name": agg.primary_model[:100]}
        },
        "Messages": {"number": agg.message_count},
        "Input tokens": {"number": agg.input_tokens},
        "Output tokens": {"number": agg.output_tokens},
        "Cache read": {"number": agg.cache_read_tokens},
        "Cache create": {"number": agg.cache_creation_tokens},
        "Cost USD": {"number": round(agg.cost_usd, 6)},
    }
    if agg.started_at:
        props["Started"] = {"date": {"start": agg.started_at}}
    if agg.last_message_at:
        props["Last message"] = {"date": {"start": agg.last_message_at}}
    return props


# ── Notion HTTP client ──────────────────────────────────────────────────────


class NotionClient:
    def __init__(self, cfg: NotionConfig) -> None:
        self.cfg = cfg
        self._headers = {
            "Authorization": f"Bearer {cfg.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def find_existing_pages(
        self, session: aiohttp.ClientSession
    ) -> dict[str, str]:
        """Query the database and return {session_id: page_id} for all rows."""
        results: dict[str, str] = {}
        cursor: str | None = None
        while True:
            payload: dict = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            url = f"{NOTION_API}/databases/{self.cfg.database_id}/query"
            async with session.post(url, headers=self._headers, json=payload) as r:
                if r.status != 200:
                    log.error("Notion query failed: %d %s", r.status, await r.text())
                    return results
                data = await r.json()
            for page in data.get("results", []):
                props = page.get("properties", {})
                sid_prop = props.get("Session ID", {})
                rich = sid_prop.get("rich_text", [])
                if rich:
                    sid = rich[0].get("plain_text") or rich[0].get("text", {}).get("content", "")
                    if sid:
                        results[sid] = page["id"]
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    async def upsert(
        self,
        session: aiohttp.ClientSession,
        agg: SessionAggregate,
        page_id: str | None,
    ) -> str | None:
        """Create or update a page for this session. Returns page_id or None."""
        properties = _build_properties(agg, self.cfg.title_property)

        if page_id:
            url = f"{NOTION_API}/pages/{page_id}"
            payload = {"properties": properties}
            async with session.patch(url, headers=self._headers, json=payload) as r:
                if r.status != 200:
                    body = await r.text()
                    log.error(
                        "Notion update failed for %s: %d %s",
                        agg.session_id, r.status, body[:300],
                    )
                    # If page was deleted/archived, fall through to create
                    if r.status in (404, 410):
                        return await self._create(session, agg, properties)
                    return None
                return page_id
        else:
            return await self._create(session, agg, properties)

    async def _create(
        self,
        session: aiohttp.ClientSession,
        agg: SessionAggregate,
        properties: dict,
    ) -> str | None:
        url = f"{NOTION_API}/pages"
        payload = {
            "parent": {"database_id": self.cfg.database_id},
            "properties": properties,
        }
        async with session.post(url, headers=self._headers, json=payload) as r:
            if r.status != 200:
                body = await r.text()
                log.error(
                    "Notion create failed for %s: %d %s",
                    agg.session_id, r.status, body[:300],
                )
                return None
            data = await r.json()
            return data.get("id")


# ── Sync loop ───────────────────────────────────────────────────────────────


async def _taryfa_sync_pass(cfg: NotionConfig) -> None:
    """Jeden przebieg syncu taryfy do Notion (auto-create bazy jeśli trzeba)."""
    from tost.taryfa import TaryfaState, scan_new_records
    from tost.taryfa_notion import resolve_taryfa_db_id, sync_taryfa_to_notion

    taryfa_state = TaryfaState()
    try:
        scan_new_records(taryfa_state)

        headers = {
            "Authorization": f"Bearer {cfg.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as http:
            db_id = await resolve_taryfa_db_id(
                http, headers, taryfa_state,
                explicit_db_id=cfg.taryfa_db_id,
                parent_page_id=cfg.taryfa_parent_page_id,
            )
        if not db_id:
            log.debug("Taryfa: brak TARYFA_NOTION_DB_ID/PARENT_PAGE_ID — pomijam sync")
            return

        created, updated, failed = await sync_taryfa_to_notion(
            taryfa_state, cfg.token, db_id,
        )
        if created or updated or failed:
            log.info(
                "Taryfa sync: %d created, %d updated, %d failed",
                created, updated, failed,
            )
    finally:
        taryfa_state.close()


async def run_sync_loop(
    cfg: NotionConfig,
    state_db: str | Path = DEFAULT_STATE_DB,
    once: bool = False,
) -> None:
    """Main sync loop — scan changed sessions every interval, push to Notion.

    Przy okazji pushuje także taryfa-buckety (co `cfg.taryfa_sync_interval`).
    """
    state = NotionSyncState(state_db)
    client = NotionClient(cfg)
    last_taryfa_sync = 0.0

    async with aiohttp.ClientSession() as http:
        # First run: backfill page_id mapping from Notion so we don't duplicate
        if not state.has_any_pages():
            log.info("Backfilling page mapping from Notion DB...")
            existing = await client.find_existing_pages(http)
            now = time.time()
            for sid, pid in existing.items():
                state.set_page_id(sid, pid, now)
            log.info("Found %d existing page(s) in Notion DB", len(existing))

        first_pass = True
        while True:
            mtimes = state.get_mtimes()
            synced = 0
            failed = 0

            for agg, new_mtime in get_changed_sessions(since_mtime=mtimes):
                page_id = state.get_page_id(agg.session_id)
                result_id = await client.upsert(http, agg, page_id)
                if result_id:
                    state.set_page_id(agg.session_id, result_id, new_mtime)
                    state.set_mtime(agg.file_path, new_mtime)
                    synced += 1
                    log.info(
                        "Synced %s [%s] %d msgs, %d in / %d out, $%.4f",
                        agg.session_id[:8],
                        agg.primary_model,
                        agg.message_count,
                        agg.input_tokens,
                        agg.output_tokens,
                        agg.cost_usd,
                    )
                else:
                    failed += 1

            if first_pass:
                log.info(
                    "Initial pass complete: %d synced, %d failed", synced, failed
                )
                first_pass = False
            elif synced or failed:
                log.info("Pass: %d synced, %d failed", synced, failed)
            else:
                log.debug("Pass: no changes")

            # Taryfa sync (rzadziej niż sesje — 15 min)
            now_ts = time.time()
            should_sync_taryfa = (
                cfg.taryfa_db_id or cfg.taryfa_parent_page_id
            ) and (once or now_ts - last_taryfa_sync >= cfg.taryfa_sync_interval)
            if should_sync_taryfa:
                try:
                    await _taryfa_sync_pass(cfg)
                except Exception as e:  # noqa: BLE001 — sync taryfy nie może ubić pętli sesji
                    log.error("Taryfa sync failed: %s", e)
                last_taryfa_sync = now_ts

            if once:
                break
            await asyncio.sleep(cfg.interval)

    state.close()


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Claude Code token usage to a Notion database",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("NOTION_TOKEN"),
        help="Notion integration token (or set NOTION_TOKEN env)",
    )
    parser.add_argument(
        "--database-id",
        default=os.environ.get("NOTION_DATABASE_ID"),
        help="Target Notion database ID (or set NOTION_DATABASE_ID env)",
    )
    parser.add_argument(
        "--interval", type=float, default=60.0,
        help="Sync interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--state-db", default=str(DEFAULT_STATE_DB),
        help=f"SQLite state file (default: {DEFAULT_STATE_DB})",
    )
    parser.add_argument(
        "--title-property", default="Session",
        help="Name of the title property in your Notion DB (default: Session)",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run one sync pass and exit",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.token:
        sys.exit("Error: --token or NOTION_TOKEN env var required")
    if not args.database_id:
        sys.exit("Error: --database-id or NOTION_DATABASE_ID env var required")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    cfg = NotionConfig(
        token=args.token,
        database_id=args.database_id,
        interval=args.interval,
        title_property=args.title_property,
    )
    try:
        asyncio.run(run_sync_loop(cfg, args.state_db, once=args.once))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    _main()
