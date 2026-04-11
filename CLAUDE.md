# TOST — Token Optimization System Tool

## Opis projektu

Narzędzie do monitorowania zużycia tokenów w Claude Code. Zbiera metryki OTLP w czasie rzeczywistym, zapisuje do SQLite, wyświetla dashboard TUI. Dodatkowo synchronizuje dane sesji do Notion.

## Architektura

```
Claude Code ──OTLP/HTTP──> Collector (:4318) ──> SQLite ──> TUI Dashboard
~/.claude/projects/*.jsonl ──> jsonl_scanner ──> notion_sync ──> Notion DB
```

## Kluczowe moduły

| Moduł | Rola |
|-------|------|
| `collector.py` | Odbiornik OTLP HTTP (aiohttp) |
| `store.py` | SQLite — cumulative → delta |
| `dashboard.py` | TUI — monitoring na żywo |
| `simulator.py` + `sim_dashboard.py` | Symulator kosztów full vs minimal CC |
| `duel.py` + `duel_dashboard.py` | Porównanie modeli (duel) |
| `trainer.py` + `trainer_dashboard.py` | Curriculum context engineering + Haiku API |
| `jsonl_scanner.py` | Parser `~/.claude/projects/*.jsonl` → agregaty sesji |
| `notion_sync.py` | Upsert sesji do Notion DB (co 60s) |
| `cost.py` | Tabele cenowe Anthropic (Opus/Sonnet/Haiku) |

## Notion sync

- **Database ID:** `6b9e6206ca1f4097b342d3ecdf11598b`
- **State:** `~/.claude/tost_notion.db` (mtimes + session_id→page_id)
- **Env vars:** `NOTION_TOKEN`, `NOTION_DATABASE_ID`
- **Uruchomienie:** `python -m tost.notion_sync` (ciągłe) lub `--once -v` (jednorazowe)
- Szczegóły konfiguracji w `NOTION_SYNC.md`

## Wymagania

- Python 3.11+
- Claude Code z OTEL włączonym w `~/.claude/settings.json` (patrz README)

## Konwencje

- CLI entry point: `tost.cli:main`, subkomendy: `monitor` (domyślna), `sim`, `train`, `duel`
- Dashboardy w Textual
- Koszt liczony z `tost.cost.calculate_cost()`
- Baza danych: SQLite (`tost.db` dla OTLP, `~/.claude/tost_notion.db` dla Notion sync)
