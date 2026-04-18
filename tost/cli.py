"""CLI entry point — TOST."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tost",
        description="TOST — Token Optimization System Tool",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Monitor (domyślny)
    subparsers.add_parser("monitor", help="Live dashboard sesji (domyślny)")

    # CC — TOST + panel Claude Code
    subparsers.add_parser("cc", help="TOST dashboard + panel terminala Claude Code")

    # Holmes — analiza anomalii
    holmes_parser = subparsers.add_parser("holmes", help="Analiza anomalii zużycia tokenów")
    holmes_parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="Data od")
    holmes_parser.add_argument("--to",   dest="date_to",   metavar="YYYY-MM-DD", help="Data do")
    holmes_parser.add_argument("--no-tui", action="store_true", help="Wyniki w terminalu zamiast TUI")

    # Ping collector (daemon)
    ping_collect_parser = subparsers.add_parser(
        "ping-collect", help="Zbieranie latency API Anthropic (daemon)")
    ping_collect_parser.add_argument("--once", action="store_true", help="Jeden pomiar i wyjście")
    ping_collect_parser.add_argument(
        "--interval", type=float, default=300.0,
        help="Interwał pomiaru w sekundach (domyślnie: 300)")
    ping_collect_parser.add_argument(
        "--notion-interval", type=float, default=1800.0,
        help="Interwał synchronizacji Notion w sekundach (domyślnie: 1800)")
    ping_collect_parser.add_argument("--verbose", "-v", action="store_true")

    # Ping viewer (TUI)
    subparsers.add_parser("ping", help="Podgląd latency API Anthropic (TUI)")

    # THC — Traffic Hours Console (Matrix TUI)
    subparsers.add_parser("thc", help="THC — Traffic Hours Console (Matrix TUI)")

    # THC Mini — 3 kropki nacisku na limity
    subparsers.add_parser("thc-mini", help="THC Mini — 3 kropki (godzina/ping/burn)")

    # Sync
    sync_parser = subparsers.add_parser("sync", help="Synchronizuj sesje do Notion")
    sync_parser.add_argument("--once", action="store_true", help="Jeden przebieg i wyjście")
    sync_parser.add_argument("--interval", type=float, default=60.0, help="Interwał w sekundach")
    sync_parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    # Ping collector
    if args.command == "ping-collect":
        from dotenv import load_dotenv
        load_dotenv()
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        )
        from tost.ping import PingConfig, run_ping_loop
        cfg = PingConfig(
            ping_interval=args.interval,
            notion_sync_interval=args.notion_interval,
            notion_token=os.environ.get("NOTION_TOKEN"),
            ping_db_id=os.environ.get("PING_NOTION_DB_ID"),
            thc_db_id=os.environ.get("THC_NOTION_DB_ID"),
        )
        try:
            asyncio.run(run_ping_loop(cfg, once=args.once))
        except KeyboardInterrupt:
            print("\nZatrzymano.")
        return

    # Ping viewer (TUI)
    if args.command == "ping":
        from tost.ping_ui import PingApp
        app = PingApp()
        app.run()
        return

    # THC — Traffic Hours Console (Matrix TUI)
    if args.command == "thc":
        from tost.thc import ThcApp
        ThcApp().run()
        return

    # THC Mini — 3 kropki nacisku na limity
    if args.command == "thc-mini":
        from tost.thc_mini import ThcMiniApp
        ThcMiniApp().run()
        return

    if args.command == "sync":
        from dotenv import load_dotenv
        load_dotenv()
        token = os.environ.get("NOTION_TOKEN")
        db_id = os.environ.get("NOTION_DATABASE_ID")
        if not token:
            sys.exit("Błąd: NOTION_TOKEN nie ustawiony (dodaj do .env lub środowiska)")
        if not db_id:
            sys.exit("Błąd: NOTION_DATABASE_ID nie ustawiony (dodaj do .env lub środowiska)")
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        )
        from tost.notion_sync import NotionConfig, run_sync_loop
        cfg = NotionConfig(
            token=token,
            database_id=db_id,
            interval=args.interval,
            taryfa_db_id=os.environ.get("TARYFA_NOTION_DB_ID"),
            taryfa_parent_page_id=os.environ.get("TARYFA_NOTION_PARENT_PAGE_ID"),
        )
        try:
            asyncio.run(run_sync_loop(cfg, once=args.once))
        except KeyboardInterrupt:
            print("\nZatrzymano.")
        return

    # Holmes — analiza anomalii
    if args.command == "holmes":
        from dotenv import load_dotenv
        load_dotenv()
        if getattr(args, "no_tui", False):
            # Tryb tekstowy
            from tost.holmes import _load_rules, run_holmes
            from tost.jsonl_scanner import scan_all_sessions
            rules = _load_rules()
            sessions = list(scan_all_sessions())
            suspects = run_holmes(sessions, rules, args.date_from, args.date_to)
            if not suspects:
                print("Brak anomalii w wybranym okresie.")
                return
            for s in suspects:
                print(f"[{s.severity}] {s.category} | {s.session.session_id[:12]} | {s.detail}")
            print(f"\nŁącznie: {len(suspects)} podejrzanych sesji.")
        else:
            from tost.holmes_ui import HolmesApp
            app = HolmesApp()
            app.run()
        return

    # CC — TOST + panel Claude Code
    if args.command == "cc":
        from tost.cc_panel import TostWithCCApp
        app = TostWithCCApp()
        app.run()
        return

    # Monitor (domyślny — też gdy brak subkomendy)
    from tost.dashboard import TostApp
    app = TostApp()
    app.run()
