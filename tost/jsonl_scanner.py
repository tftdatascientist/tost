"""Scan ~/.claude/projects/ JSONL files for token usage.

Claude Code writes one JSONL file per session to:
    ~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl

Each `assistant`-typed line carries:
    message.model
    message.usage.input_tokens
    message.usage.output_tokens
    message.usage.cache_read_input_tokens
    message.usage.cache_creation_input_tokens

We aggregate per session (one row per JSONL file) and tag each row with:
    - session_id   (filename stem)
    - project      (decoded cwd path)
    - timestamps   (earliest + latest message)
    - cost_usd     (calculated from tost.cost pricing tables)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

log = logging.getLogger("tost.jsonl_scanner")

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Skip pathologically large session files (see anthropics/claude-code#22365)
MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class SessionAggregate:
    """Aggregated token usage for a single session JSONL file."""

    session_id: str
    project: str                # decoded path, e.g. /Users/pawel/projekt-alpha
    project_encoded: str        # raw directory name
    file_path: str
    primary_model: str = "unknown"   # model that produced most output tokens
    models: set[str] = field(default_factory=set)
    started_at: str = ""             # earliest ISO timestamp
    last_message_at: str = ""        # latest ISO timestamp
    message_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_creation_tokens
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def decode_project_path(encoded: str) -> str:
    """Best-effort reverse of Claude Code's path encoding.

    Anthropic encodes the absolute cwd by replacing every non-alphanumeric
    character with '-'. The reverse is lossy (we can't tell '-' from '_' from
    '/'), so this is for display only.
    """
    if encoded.startswith("-"):
        return "/" + encoded[1:].replace("-", "/")
    return encoded.replace("-", "/")


def iter_jsonl_records(file_path: Path) -> Iterator[dict]:
    """Yield each parsed JSON line from a JSONL file. Skips bad lines."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        log.debug("Could not read %s: %s", file_path, e)
        return


def extract_usage(record: dict) -> dict | None:
    """Extract usage info from an assistant message record. Returns None if N/A."""
    if record.get("type") != "assistant":
        return None
    msg = record.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "model": str(msg.get("model", "unknown")),
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
    }


# ── Scanning ────────────────────────────────────────────────────────────────


def scan_session_file(file_path: Path) -> SessionAggregate | None:
    """Aggregate all token usage in a single session JSONL file."""
    from tost.cost import calculate_cost

    project_encoded = file_path.parent.name
    session_id = file_path.stem  # filename without .jsonl

    agg = SessionAggregate(
        session_id=session_id,
        project=decode_project_path(project_encoded),
        project_encoded=project_encoded,
        file_path=str(file_path),
    )

    model_output_totals: dict[str, int] = {}  # for picking primary model

    for record in iter_jsonl_records(file_path):
        ts = record.get("timestamp", "")
        if isinstance(ts, str) and ts:
            if not agg.started_at or ts < agg.started_at:
                agg.started_at = ts
            if not agg.last_message_at or ts > agg.last_message_at:
                agg.last_message_at = ts

        usage = extract_usage(record)
        if not usage:
            continue

        agg.message_count += 1
        agg.input_tokens += usage["input_tokens"]
        agg.output_tokens += usage["output_tokens"]
        agg.cache_read_tokens += usage["cache_read_tokens"]
        agg.cache_creation_tokens += usage["cache_creation_tokens"]
        agg.models.add(usage["model"])
        model_output_totals[usage["model"]] = (
            model_output_totals.get(usage["model"], 0) + usage["output_tokens"]
        )

        agg.cost_usd += calculate_cost(
            model=usage["model"],
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_read_tokens=usage["cache_read_tokens"],
            cache_creation_tokens=usage["cache_creation_tokens"],
        )

    if model_output_totals:
        agg.primary_model = max(model_output_totals.items(), key=lambda kv: kv[1])[0]

    return agg if agg.message_count > 0 else None


def scan_all_sessions(root: Path | None = None) -> Iterator[SessionAggregate]:
    """Scan every JSONL file under ~/.claude/projects/ once."""
    base = root or CLAUDE_PROJECTS_DIR
    if not base.is_dir():
        log.warning("Claude projects dir not found: %s", base)
        return
    for project_dir in sorted(base.iterdir()):
        if not project_dir.is_dir():
            continue
        for session_file in sorted(project_dir.glob("*.jsonl")):
            try:
                if session_file.stat().st_size > MAX_FILE_BYTES:
                    log.warning(
                        "Skipping oversized session file: %s (%.1f MB)",
                        session_file, session_file.stat().st_size / 1024 / 1024,
                    )
                    continue
            except OSError:
                continue
            agg = scan_session_file(session_file)
            if agg:
                yield agg


def get_changed_sessions(
    root: Path | None = None,
    since_mtime: dict[str, float] | None = None,
) -> Iterator[tuple[SessionAggregate, float]]:
    """Yield only sessions whose JSONL file has been modified since last scan.

    Args:
        root: defaults to ~/.claude/projects/
        since_mtime: {file_path: last_seen_mtime}

    Yields:
        (aggregate, current_mtime) tuples for changed/new files only.
    """
    base = root or CLAUDE_PROJECTS_DIR
    if not base.is_dir():
        return
    seen = since_mtime or {}

    for project_dir in sorted(base.iterdir()):
        if not project_dir.is_dir():
            continue
        for session_file in sorted(project_dir.glob("*.jsonl")):
            try:
                stat = session_file.stat()
            except OSError:
                continue

            mtime = stat.st_mtime
            prev = seen.get(str(session_file))
            if prev is not None and prev >= mtime:
                continue

            if stat.st_size > MAX_FILE_BYTES:
                log.warning(
                    "Skipping oversized session file: %s (%.1f MB)",
                    session_file, stat.st_size / 1024 / 1024,
                )
                continue

            agg = scan_session_file(session_file)
            if not agg:
                continue

            # Re-stat after read so we capture the post-read mtime
            try:
                final_mtime = session_file.stat().st_mtime
            except OSError:
                final_mtime = mtime

            yield agg, final_mtime
