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
        description="TOST — Token Overhead Surveillance Tool",
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

    # TUI mode — collector in background thread, dashboard in main thread
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
