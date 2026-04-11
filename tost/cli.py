"""CLI entry point — wires collector + dashboard together."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

from tost.collector import run_collector
from tost.config import load_config
from tost.store import Store


def _run_collector_thread(store: Store, host: str, port: int) -> None:
    """Run the OTLP collector in a background thread with its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_collector(store, host, port))
    loop.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tost",
        description="TOST — Token Optimization System Tool",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Default monitor command
    mon = subparsers.add_parser("monitor", help="Live token monitoring (default)")
    mon.add_argument("--config", "-c", help="Path to tost.toml")
    mon.add_argument("--port", "-p", type=int, help="OTLP receiver port (default: 4318)")
    mon.add_argument("--session", "-s", help="Filter to specific session ID")
    mon.add_argument("--db", help="SQLite database path")
    mon.add_argument("--no-tui", action="store_true", help="Run collector only, no dashboard")
    mon.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    # Simulation command
    subparsers.add_parser("sim", help="Cost simulation — compare full vs minimal CC")

    # Trainer command
    subparsers.add_parser("train", help="Context engineering trainer (powered by Haiku)")

    # Duel command
    subparsers.add_parser("duel", help="Duel mode — two profiles compare CC configs & costs")

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Sync session usage to Notion database")
    sync_parser.add_argument("--once", action="store_true", help="Run one sync pass and exit")
    sync_parser.add_argument("--interval", type=float, default=60.0, help="Sync interval in seconds")
    sync_parser.add_argument("--verbose", "-v", action="store_true")

    # Also support old-style flags at top level for backwards compat
    parser.add_argument("--config", "-c", help=argparse.SUPPRESS, default=None)
    parser.add_argument("--port", "-p", type=int, help=argparse.SUPPRESS, default=None)
    parser.add_argument("--session", "-s", help=argparse.SUPPRESS, default=None)
    parser.add_argument("--db", help=argparse.SUPPRESS, default=None)
    parser.add_argument("--no-tui", action="store_true", help=argparse.SUPPRESS, default=False)
    parser.add_argument("--verbose", "-v", action="store_true", help=argparse.SUPPRESS, default=False)

    args = parser.parse_args()

    # Simulation mode
    if args.command == "sim":
        from tost.sim_dashboard import SimDashboard
        app = SimDashboard()
        app.run()
        return

    # Sync mode
    if args.command == "sync":
        import os
        from dotenv import load_dotenv
        load_dotenv()
        token = os.environ.get("NOTION_TOKEN")
        db_id = os.environ.get("NOTION_DATABASE_ID")
        if not token:
            sys.exit("Error: NOTION_TOKEN not set (add to .env or environment)")
        if not db_id:
            sys.exit("Error: NOTION_DATABASE_ID not set (add to .env or environment)")
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        )
        from tost.notion_sync import NotionConfig, run_sync_loop
        cfg = NotionConfig(token=token, database_id=db_id, interval=args.interval)
        try:
            asyncio.run(run_sync_loop(cfg, once=args.once))
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    # Duel mode
    if args.command == "duel":
        from tost.duel_dashboard import DuelApp
        app = DuelApp()
        app.run()
        return

    # Trainer mode
    if args.command == "train":
        from tost.trainer_dashboard import TrainerApp
        app = TrainerApp()
        app.run()
        return

    # Monitor mode (default)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    config = load_config(args.config)
    if args.port:
        config.collector.port = args.port
    if args.db:
        config.database.path = args.db

    store = Store(config.database.path)

    if args.no_tui:
        # Headless mode — just run collector
        print(f"TOST collector listening on {config.collector.host}:{config.collector.port}")
        print("Press Ctrl+C to stop.")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run_collector(store, config.collector.host, config.collector.port))
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            store.close()
        return

    # TUI mode — suppress aiohttp access logs so they don't bleed into the TUI
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # Collector in background thread, dashboard in main thread
    collector_thread = threading.Thread(
        target=_run_collector_thread,
        args=(store, config.collector.host, config.collector.port),
        daemon=True,
    )
    collector_thread.start()

    from tost.dashboard import TostApp

    app = TostApp(store=store, config=config)
    if args.session:
        app.set_session_filter(args.session)

    try:
        app.run()
    finally:
        store.close()
