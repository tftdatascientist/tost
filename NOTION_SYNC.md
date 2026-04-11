# TOST → Notion sync — setup

Two new files dropped into `tost/`:
- `tost/jsonl_scanner.py` — reads `~/.claude/projects/*.jsonl` (Claude Code's
  built-in session log) and aggregates token usage per session.
- `tost/notion_sync.py` — pushes those aggregates to a Notion database every
  60 s, upserting one page per session.

No changes are required to existing TOST modules — `notion_sync` is runnable
standalone via `python -m tost.notion_sync`. CLI integration is optional and
shown at the bottom of this file.

---

## 1. Create the Notion database

Create a database with **exactly these property names and types** (case sensitive):

| Property        | Type        | Notes                              |
|-----------------|-------------|------------------------------------|
| `Session`       | Title       | This is the title column           |
| `Session ID`    | Text        | Unique key — used to upsert        |
| `Project`       | Text        | Decoded project path               |
| `Model`         | Select      | Auto-populates as new models appear|
| `Started`       | Date        | Earliest message timestamp         |
| `Last message`  | Date        | Latest message timestamp           |
| `Messages`      | Number      | Assistant message count            |
| `Input tokens`  | Number      |                                    |
| `Output tokens` | Number      |                                    |
| `Cache read`    | Number      |                                    |
| `Cache create`  | Number      |                                    |
| `Cost USD`      | Number (USD format) | Calculated from tost.cost  |

If your title property is named something other than `Session`, pass
`--title-property "Your Title Name"` when running.

## 2. Get an integration token

1. Go to <https://www.notion.so/profile/integrations>
2. Create a new internal integration → copy the secret (`secret_…` or `ntn_…`)
3. Open your database → ⋯ menu → Connections → add the integration
4. Get the database ID from the URL — it's the 32-char chunk after the
   workspace name and before `?v=`:
   `https://www.notion.so/myws/<DATABASE_ID>?v=...`

## 3. Run the sync

```bash
export NOTION_TOKEN=secret_xxxxxxxxxxxx
export NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Default 60 s interval, runs forever
python -m tost.notion_sync

# Single pass, useful for cron / debugging
python -m tost.notion_sync --once -v

# Custom interval
python -m tost.notion_sync --interval 30
```

State (file mtimes + session→page_id mapping) is stored in
`~/.claude/tost_notion.db` so the loop is restart-safe and won't duplicate pages.

## 4. (Optional) Wire into the `tost` CLI

If you want `tost sync` instead of `python -m tost.notion_sync`, add this to
`tost/cli.py` inside `main()` next to the other `subparsers.add_parser` calls:

```python
sync = subparsers.add_parser("sync", help="Sync token usage to Notion every 60s")
sync.add_argument("--token", default=None)
sync.add_argument("--database-id", default=None)
sync.add_argument("--interval", type=float, default=60.0)
sync.add_argument("--once", action="store_true")
```

And dispatch (next to the `if args.command == "sim":` block):

```python
if args.command == "sync":
    import asyncio, os
    from tost.notion_sync import NotionConfig, run_sync_loop, DEFAULT_STATE_DB

    token = args.token or os.environ.get("NOTION_TOKEN")
    db_id = args.database_id or os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        raise SystemExit("Set NOTION_TOKEN and NOTION_DATABASE_ID env vars")

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    cfg = NotionConfig(token=token, database_id=db_id, interval=args.interval)
    try:
        asyncio.run(run_sync_loop(cfg, DEFAULT_STATE_DB, once=args.once))
    except KeyboardInterrupt:
        print("\nStopped.")
    return
```

## 5. (Optional) Run sync alongside the live dashboard

The collector and the Notion sync can coexist — they read different data
sources (collector = OTLP push, sync = JSONL scrape). Run them in two
terminals, or background one:

```bash
tost monitor &        # OTLP receiver + TUI
tost sync             # JSONL → Notion every 60 s
```

---

## How it works

1. **Scanner** walks `~/.claude/projects/<encoded-cwd>/*.jsonl`, parses each
   line, picks `type=="assistant"` records, and sums up `message.usage` fields.
   It also computes USD cost from `tost.cost.calculate_cost`.
2. **State** (`~/.claude/tost_notion.db`) tracks the last-seen mtime per
   JSONL file. Only changed files are rescanned each pass — this is cheap even
   for hundreds of sessions.
3. **First run** queries the Notion DB once to backfill `session_id → page_id`
   so existing rows are updated, not duplicated.
4. **Each pass** (default 60 s) upserts changed sessions: PATCH if we already
   know the page_id, POST otherwise.

Skipped: any session JSONL file >100 MB (rare, but see
[anthropics/claude-code#22365](https://github.com/anthropics/claude-code/issues/22365)).
