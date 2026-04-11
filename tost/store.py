"""SQLite storage for OTLP metric snapshots."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MetricSnapshot:
    session_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float


@dataclass
class StoredSnapshot:
    id: int
    received_at: str
    session_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    delta_input: int
    delta_output: int
    delta_cache_read: int
    delta_cache_creation: int
    delta_cost: float


SCHEMA = """\
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    session_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    delta_input INTEGER NOT NULL DEFAULT 0,
    delta_output INTEGER NOT NULL DEFAULT 0,
    delta_cache_read INTEGER NOT NULL DEFAULT 0,
    delta_cache_creation INTEGER NOT NULL DEFAULT 0,
    delta_cost REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_session ON metric_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_received ON metric_snapshots(received_at);
"""


class Store:
    def __init__(self, db_path: str | Path = "tost.db") -> None:
        self._lock = threading.Lock()
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def insert(self, snap: MetricSnapshot) -> None:
        """Insert a cumulative snapshot, computing deltas from previous."""
        with self._lock:
            prev = self._conn.execute(
                "SELECT input_tokens, output_tokens, cache_read_tokens, "
                "cache_creation_tokens, cost_usd FROM metric_snapshots "
                "WHERE session_id = ? AND model = ? ORDER BY id DESC LIMIT 1",
                (snap.session_id, snap.model),
            ).fetchone()

            if prev:
                d_in = max(0, snap.input_tokens - prev["input_tokens"])
                d_out = max(0, snap.output_tokens - prev["output_tokens"])
                d_cr = max(0, snap.cache_read_tokens - prev["cache_read_tokens"])
                d_cc = max(0, snap.cache_creation_tokens - prev["cache_creation_tokens"])
                d_cost = max(0.0, snap.cost_usd - prev["cost_usd"])
            else:
                # First snapshot for session — no delta
                d_in = d_out = d_cr = d_cc = 0
                d_cost = 0.0

            self._conn.execute(
                "INSERT INTO metric_snapshots "
                "(session_id, model, input_tokens, output_tokens, "
                "cache_read_tokens, cache_creation_tokens, cost_usd, "
                "delta_input, delta_output, delta_cache_read, "
                "delta_cache_creation, delta_cost) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snap.session_id, snap.model,
                    snap.input_tokens, snap.output_tokens,
                    snap.cache_read_tokens, snap.cache_creation_tokens,
                    snap.cost_usd,
                    d_in, d_out, d_cr, d_cc, d_cost,
                ),
            )
            self._conn.commit()

    def get_session_totals(self, session_id: str | None = None) -> dict | None:
        """Get latest cumulative totals for a session (or the most recent session).

        Aggregates across all models within the session. Returns the primary
        model (highest cost) in the 'model' field.
        """
        with self._lock:
            sid = session_id
            if not sid:
                row = self._conn.execute(
                    "SELECT session_id FROM metric_snapshots ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return None
                sid = row["session_id"]

            # Get latest snapshot per model within the session
            rows = self._conn.execute(
                "SELECT model, input_tokens, output_tokens, "
                "cache_read_tokens, cache_creation_tokens, cost_usd "
                "FROM metric_snapshots WHERE session_id = ? AND id IN ("
                "  SELECT MAX(id) FROM metric_snapshots "
                "  WHERE session_id = ? GROUP BY model"
                ")",
                (sid, sid),
            ).fetchall()
            if not rows:
                return None

            totals = {
                "session_id": sid,
                "model": "unknown",
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cost_usd": 0.0,
            }
            best_cost = -1.0
            for r in rows:
                totals["input_tokens"] += r["input_tokens"]
                totals["output_tokens"] += r["output_tokens"]
                totals["cache_read_tokens"] += r["cache_read_tokens"]
                totals["cache_creation_tokens"] += r["cache_creation_tokens"]
                totals["cost_usd"] += r["cost_usd"]
                if r["cost_usd"] > best_cost:
                    best_cost = r["cost_usd"]
                    totals["model"] = r["model"]
            return totals

    def get_session_deltas(
        self, session_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Get delta snapshots (non-zero deltas only) for message table."""
        with self._lock:
            if session_id:
                rows = self._conn.execute(
                    "SELECT * FROM metric_snapshots "
                    "WHERE session_id = ? AND "
                    "(delta_input > 0 OR delta_output > 0 OR delta_cache_read > 0 "
                    "OR delta_cache_creation > 0) "
                    "ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM metric_snapshots "
                    "WHERE delta_input > 0 OR delta_output > 0 OR delta_cache_read > 0 "
                    "OR delta_cache_creation > 0 "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_all_sessions(self) -> list[dict]:
        """Get summary for all sessions."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, model, "
                "MAX(input_tokens) as input_tokens, "
                "MAX(output_tokens) as output_tokens, "
                "MAX(cache_read_tokens) as cache_read_tokens, "
                "MAX(cache_creation_tokens) as cache_creation_tokens, "
                "MAX(cost_usd) as cost_usd, "
                "MIN(received_at) as started_at, "
                "MAX(received_at) as last_seen, "
                "COUNT(*) as snapshot_count "
                "FROM metric_snapshots GROUP BY session_id "
                "ORDER BY last_seen DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_active_session_id(self) -> str | None:
        """Get the session_id of the most recent snapshot."""
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id FROM metric_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["session_id"] if row else None
