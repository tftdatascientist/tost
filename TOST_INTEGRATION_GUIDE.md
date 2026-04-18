# TOST — Przewodnik integracyjny

> Architektura, moduły, schematy danych i punkty integracji narzędzia
> TOST (Token Optimization System Tool). Dokument aktualizowany po
> rewrite'cie projektu z architektury OTLP na czystą analizę JSONL.

---

## 1. Czym jest TOST

TOST to lokalne narzędzie Pythonowe dla użytkowników **Claude Max**
(nie API). Żaden moduł nie wymaga `ANTHROPIC_API_KEY`. Jedyny ruch
sieciowy to:

1. HEAD na `api.anthropic.com` i `status.anthropic.com` w `ping.py`
   (bez uwierzytelniania)
2. Opcjonalny sync do Notion (`NOTION_TOKEN`)

Źródło prawdy o sesjach to `~/.claude/projects/**/*.jsonl` —
append-only pliki zapisywane przez Claude Code. TOST skanuje je
inkrementalnie po byte-offset (`f.tell()` w trybie binarnym).

### Funkcje

1. **Agregacja sesji** — parse JSONL → dashboard TUI + Notion sesje
2. **Holmes** — 6 reguł anomalii (cache invalidation, overflow,
   think waste, MCP overload, cost spike, high cache creation)
3. **Ping** — latency api.anthropic.com co 5 min (SQLite + Notion
   hourly + THC 15-min agregaty), sonar po każdym pingu
4. **THC — Traffic Hours Console** — Matrix TUI, tiery serwerowe
   (GREEN/YELLOW/ORANGE/RED wg godziny UTC), panel Taryfa
5. **Taryfa** — burn-rate detektor tokenów na poziomie godziny UTC,
   porównanie z 7-dniowym baselinem tej samej godziny doby
6. **Notion sync** — sesje (co 60s) + kubełki taryfy (co 15 min)

---

## 2. Architektura

```
┌── DANE ŹRÓDŁOWE ──────────────────────────────────────────────┐
│ ~/.claude/projects/**/*.jsonl        api.anthropic.com (HEAD) │
└──────────────────┬────────────────────────────────┬───────────┘
                   │                                │
       ┌───────────┴───────────┐             ┌──────┴──────┐
       ▼                       ▼             ▼             │
  jsonl_scanner           taryfa.scan    ping.py           │
  (per session)           (per hour)     (daemon 5 min)    │
       │                       │             │             │
       ▼                       ▼             ▼             ▼
  dashboard/holmes      tost_taryfa.db  tost_ping.db   sound.py
  (TUI + Notion)        (SQLite WAL)    (SQLite WAL)   (sonar)
       │                       │             │
       ▼                       ▼             │
  notion_sync ◄─────► taryfa_notion          │
  Notion: Sesje       Notion: Taryfa         │
                                             ▼
                                          thc.py (Matrix TUI)
                                          ← 3 SQLite + TOML
```

Żaden proces nie słucha na porcie — TOST jest wyłącznie konsumentem
lokalnych plików i (opcjonalnie) klientem Notion API.

---

## 3. Moduły

| Moduł | Plik | Rola |
|-------|------|------|
| **CLI** | `tost/cli.py` | Argparse dispatcher — 7 subkomend |
| **Dashboard** | `tost/dashboard.py` | Textual TUI — lista sesji |
| **CC Panel** | `tost/cc_panel.py` | TUI: TOST + terminal `cc` |
| **JSONL Scanner** | `tost/jsonl_scanner.py` | Parser JSONL → `SessionAggregate` |
| **Notion Sync** | `tost/notion_sync.py` | Upsert sesji + orkiestracja taryfa sync |
| **Cost** | `tost/cost.py` | Tabele cenowe Anthropic |
| **Holmes** | `tost/holmes.py` | Silnik 6 reguł anomalii |
| **Holmes UI** | `tost/holmes_ui.py` | TUI wyboru okresu + push do Notion |
| **Holmes rules** | `tost/holmes_rules.toml` | Progi reguł (edytowalne) |
| **Ping** | `tost/ping.py` | Daemon latency + sonar trigger |
| **Ping UI** | `tost/ping_ui.py` | Viewer latency (readonly TUI) |
| **Sound** | `tost/sound.py` | Proceduralny WAV sonar + toggle |
| **THC** | `tost/thc.py` | Matrix TUI — tiery + taryfa + widgety |
| **THC Tiers** | `tost/thc_tiers.py` | Logika GREEN..RED wg godziny UTC |
| **THC Tiers TOML** | `tost/thc_tiers.toml` | Mapowanie godzina → tier |
| **Taryfa** | `tost/taryfa.py` | Burn-rate, baseline 7d, z-score MAD |
| **Taryfa Notion** | `tost/taryfa_notion.py` | Auto-create DB + sync kubełków |
| **Taryfa progs** | `tost/taryfa_thresholds.toml` | Ratio + z-score progs |

---

## 4. CLI — pełna specyfikacja

```
tost [command] [options]

Commands:
  monitor (default)   Live dashboard sesji
  cc                  Dashboard + terminal Claude Code (cc)
  holmes              Analizator anomalii (TUI lub --no-tui)
  ping-collect        Daemon pomiaru latency (co 5 min)
  ping                Viewer latency (TUI readonly)
  thc                 Traffic Hours Console (Matrix TUI)
  sync                Notion sync — sesje + taryfa (daemon)

Holmes options:
  --from YYYY-MM-DD
  --to   YYYY-MM-DD
  --no-tui            Tryb tekstowy zamiast TUI

Ping-collect options:
  --once              Jeden pomiar i wyjście
  --interval N        Interwał pomiarów (default: 300s)
  --notion-interval N Interwał sync Notion (default: 1800s)
  --verbose, -v

Sync options:
  --once              Jeden przebieg i wyjście
  --interval N        Interwał sesji (default: 60s)
  --verbose, -v
```

Entry point: `tost.cli:main` (w `pyproject.toml` → `[project.scripts]`).

---

## 5. Zmienne środowiskowe

Wszystko w `.env` w katalogu projektu. Pliki CLI same ładują `.env`
przez `python-dotenv`.

| Var | Wymagana | Moduł | Opis |
|-----|----------|-------|------|
| `NOTION_TOKEN` | do syncu | wszystkie | Token integracji Notion |
| `NOTION_DATABASE_ID` | `tost sync` | sesje | Baza sesji CC |
| `HOLMES_SUSPECTS_DB_ID` | Holmes sync | holmes | Baza anomalii |
| `PING_NOTION_DB_ID` | opcjonalna | ping | Hourly aggregaty |
| `THC_NOTION_DB_ID` | opcjonalna | ping → THC | 15-min buckety |
| `TARYFA_NOTION_DB_ID` | jedna z 2 | taryfa | Istniejąca baza taryfy |
| `TARYFA_NOTION_PARENT_PAGE_ID` | jedna z 2 | taryfa | Parent page do auto-create bazy |

Brak jakiejkolwiek zmiennej Notion → odpowiedni moduł po prostu
pomija sync; TUI i lokalny zapis SQLite działają niezależnie.

---

## 6. Schematy SQLite

### 6.1. `~/.claude/tost_notion.db` (notion_sync)

```sql
CREATE TABLE notion_file_mtimes (
    file_path TEXT PRIMARY KEY,
    mtime     REAL NOT NULL
);

CREATE TABLE notion_pages (
    session_id  TEXT PRIMARY KEY,
    page_id     TEXT NOT NULL,
    last_synced REAL NOT NULL DEFAULT 0
);
```

### 6.2. `~/.claude/tost_ping.db` (ping)

```sql
CREATE TABLE ping_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    target          TEXT NOT NULL,     -- 'api' | 'status'
    dns_ms          REAL,
    connect_ms      REAL,
    ttfb_ms         REAL,
    total_ms        REAL,
    http_status     INTEGER,
    error           TEXT,
    synced_notion   INTEGER DEFAULT 0,
    synced_thc      INTEGER DEFAULT 0
);
-- WAL mode, idx(timestamp), idx(target)
```

### 6.3. `~/.claude/tost_taryfa.db` (taryfa)

```sql
CREATE TABLE taryfa_hourly (
    date                  TEXT NOT NULL,  -- YYYY-MM-DD (UTC)
    hour                  INTEGER NOT NULL, -- 0-23
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,
    cache_read_tokens     INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cost_usd              REAL DEFAULT 0.0,
    message_count         INTEGER DEFAULT 0,
    PRIMARY KEY (date, hour)
);

CREATE TABLE taryfa_file_offsets (
    file_path TEXT PRIMARY KEY,
    offset    INTEGER NOT NULL
);

CREATE TABLE taryfa_notion_pages (
    date             TEXT NOT NULL,
    hour             INTEGER NOT NULL,
    page_id          TEXT NOT NULL,
    last_synced_total INTEGER NOT NULL,
    synced_at        TEXT NOT NULL,
    PRIMARY KEY (date, hour)
);

CREATE TABLE taryfa_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

---

## 7. Notion DB — schematy

### 7.1. Sesje (`NOTION_DATABASE_ID`)

Pola (utrzymywane ręcznie lub przez `notion_sync`):
- `Session ID` (title)
- `Project`, `Model` (rich_text / select)
- `Started at`, `Last message` (date)
- `Input tokens`, `Output tokens`, `Cache read`, `Cache creation`,
  `Messages` (number)
- `Cost USD` (number, dollar)

### 7.2. Taryfa (`TARYFA_NOTION_DB_ID` — auto-create)

Tworzona przez `_ensure_taryfa_db()` pod `TARYFA_NOTION_PARENT_PAGE_ID`:
- `Slot` (title) — `YYYY-MM-DD HH:00 UTC`
- `Date` (date), `Hour` (number)
- `Tokens`, `Cost USD` (number/dollar)
- `Baseline median`, `Baseline p90`, `Baseline samples` (number)
- `Burn ratio`, `Z-score` (number)
- `Tariff` (select: ZIELONA/ZOLTA/POMARANCZOWA/CZERWONA + kolory)
- `Server tier` (select: GREEN/YELLOW/ORANGE/RED + kolory)
- `Synced at` (date)

### 7.3. Suspects Holmesa (`HOLMES_SUSPECTS_DB_ID`)

Auto-create przez `_ensure_suspects_db()`:
- `Session ID` (title)
- `Category`, `Severity`, `Detail` (select/rich_text)
- `Tokens`, `Cost USD` (number)
- `Started at` (date), `Model` (select)

### 7.4. Ping hourly (`PING_NOTION_DB_ID`)

- `Slot` (title — YYYY-MM-DD HH:00)
- `Date`, `Hour`, `Target`, `Avg TTFB`, `Avg total`,
  `P50/P95`, `Samples`, `Errors`

### 7.5. THC 15-min (`THC_NOTION_DB_ID`)

- `Slot` (title — YYYY-MM-DD HH:MM)
- `Date`, `Hour`, `Minute`, `Target`, `Tier`, `Avg TTFB`,
  `Avg total`, `Sample count`, `Error count`

---

## 8. Algorytm Taryfy

```
baseline_hourly = tokens dla tej samej godziny doby
                  z ostatnich 7 dni (pomijając dzisiejszą)

jeśli len(baseline_hourly) < 5:
    baseline_all = tokens dla wszystkich godzin z 7 dni
    użyj baseline_all zamiast baseline_hourly

median, p90 = statystyki na baselinie
mad = median(|x - median|)
scale = 1.4826 * mad   (≈ sigma dla normalnego rozkładu)

elapsed = (now - start_of_hour) / 3600
jeśli elapsed_seconds < 120:  # bezpiecznik na pierwsze 2 min
    taryfa = GREEN

ratio  = tokens_so_far / (median * elapsed_fraction)
z      = (tokens_so_far - median * elapsed_fraction) / (scale * elapsed_fraction)

t_ratio = bucket z ratio vs (green/yellow/orange_ratio_max)
t_z     = bucket z z vs (green/yellow/orange_z_max)
t_p90   = RED jeśli tokens_so_far > p90_multiplier_red * p90

taryfa = MAX severity z (t_ratio, t_z, t_p90)
```

Progi: `tost/taryfa_thresholds.toml`:

```toml
baseline_days = 7
min_samples = 5
min_elapsed_seconds = 120

green_ratio_max = 1.0
yellow_ratio_max = 1.5
orange_ratio_max = 2.5

green_z_max = 1.0
yellow_z_max = 2.0
orange_z_max = 3.0

p90_multiplier_red = 2.0
```

---

## 9. Integracja z innymi narzędziami

### 9.1. Odczyt sesji programowo

```python
from tost.jsonl_scanner import scan_all_sessions

for agg in scan_all_sessions():
    print(f"{agg.session_id[:12]} | {agg.primary_model} "
          f"| {agg.total_tokens:,} tok | ${agg.cost_usd:.3f}")
```

### 9.2. Odczyt taryfy bieżącej

```python
from datetime import datetime, timezone
from tost.taryfa import TaryfaState, scan_new_records, compute_tariff

state = TaryfaState()
scan_new_records(state)
reading = compute_tariff(state, datetime.now(timezone.utc))
print(f"{reading.taryfa.name}: ratio={reading.ratio:.2f}, "
      f"z={reading.z_score:.2f}")
state.close()
```

### 9.3. Odczyt tiera serwerowego

```python
from datetime import datetime, timezone
from tost.thc_tiers import get_tier, load_tiers

tier = get_tier(datetime.now(timezone.utc))  # Tier.GREEN..RED
```

### 9.4. Toggle sonaru

```python
from tost.sound import is_enabled, set_enabled, toggle_enabled

toggle_enabled()   # ON → OFF, OFF → ON (marker w ~/.claude/)
```

### 9.5. Ręczny sync taryfy do Notion

```python
import asyncio, os
from tost.taryfa import TaryfaState
from tost.taryfa_notion import sync_taryfa_to_notion

async def main():
    state = TaryfaState()
    created, updated, failed = await sync_taryfa_to_notion(
        state,
        notion_token=os.environ["NOTION_TOKEN"],
        database_id=os.environ["TARYFA_NOTION_DB_ID"],
        lookback_days=2,
    )
    print(f"created={created} updated={updated} failed={failed}")
    state.close()

asyncio.run(main())
```

---

## 10. Launcher i skróty Windows

### 10.1. Unified launcher (rekomendowany)

```powershell
powershell -ExecutionPolicy Bypass -File create-shortcut-launcher.ps1
```

Tworzy `TOST Launcher.lnk` → menu z wyborem modułu + pętla powrotu
po zamknięciu. Używa `tost-launcher.ps1` (PowerShell 5.1, UTF-8 BOM,
auto-load `.env`, `$exit` flag zamiast `break` w switch-in-while).

### 10.2. Skróty pojedyncze (opcjonalne)

| Skrypt | Skrót |
|--------|-------|
| `create-shortcut.ps1` | `TOST.lnk` (monitor) |
| `create-shortcut-cc.ps1` | `TOST CC.lnk` (monitor + terminal cc) |
| `create-shortcut-holmes.ps1` | `Holmes.lnk` |
| `create-shortcut-thc.ps1` | `THC.lnk` |
| `create-shortcut-ping.ps1` | `TOST Ping.lnk` |
| `create-shortcut-notion-sync.ps1` | `TOST Notion Sync.lnk` |

### 10.3. Ping autostart

```powershell
.\register-ping-autostart.ps1
```

Instaluje `.lnk` w `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
(nie wymaga admina) — ping-collect startuje przy każdym zalogowaniu.

---

## 11. Pliki i ścieżki

| Plik | Ścieżka | Rola |
|------|---------|------|
| Sesje CC | `~/.claude/projects/<encoded-cwd>/*.jsonl` | Append-only logi |
| Notion state | `~/.claude/tost_notion.db` | mtimes + session → page |
| Ping state | `~/.claude/tost_ping.db` | Pomiary + flagi sync |
| Taryfa state | `~/.claude/tost_taryfa.db` | Kubełki + offsety |
| Sonar WAV cache | `~/.claude/tost_sonar.wav` | ~10 KB WAV |
| Sonar marker | `~/.claude/tost_sonar_disabled` | Obecność = OFF |
| Credentiale | `<project>/.env` | NOTION_TOKEN, DB ID-y |
| Tiery godz. | `tost/thc_tiers.toml` | UTC → tier |
| Reguły Holmesa | `tost/holmes_rules.toml` | Progi anomalii |
| Progi taryfy | `tost/taryfa_thresholds.toml` | Ratio/z-score |

---

## 12. Gotcha i quirki

- `python -m tost.cli` nie daje outputu — używaj `tost <subkomenda>`
  albo `python -m tost <subkomenda>`.
- Windows Startup `.lnk` nie wymaga admina; `schtasks /SC ONLOGON`
  i `Register-ScheduledTask` — tak.
- `schtasks` w Git Bash interpretuje `/` jako ścieżkę — wywołuj
  przez `powershell -Command "schtasks ..."`.
- SQLite migracje: `PRAGMA table_info(...)` + osobna lista
  `ADDABLE_COLUMNS` — zawsze dodawaj brakujące kolumny niezależnie
  od wersji schematu.
- `aiohttp.TraceConfig` nie rozdziela TCP i TLS — `on_connection_create`
  obejmuje oba; TTFB = `request_end - request_start`.
- `ping.py` tworzy **nową** sesję `aiohttp` per pomiar (nie reużywa
  pool) — wymagane dla pełnego DNS+Connect+TTFB.
- Sonar gra tylko dla targetu `api` (nie duplikuje na parę api+status).
- PowerShell 5.1 — pliki `.ps1` zapisywać z **UTF-8 BOM**; w pętli
  `while + switch` używaj `$exit` flagi zamiast `break` (który ma
  niejednoznaczne zachowanie między switchem a while'em).

---

## 13. Zależności

```toml
# pyproject.toml
requires-python = ">=3.11"
dependencies = [
    "aiohttp>=3.9",       # Notion API + ping
    "textual>=0.70",      # TUI wszystkich interfejsów
    "python-dotenv>=1.0", # .env loader
]
```

`tomllib` — stdlib. `winsound` — stdlib (Windows). `statistics`,
`sqlite3`, `asyncio`, `struct`, `wave` — stdlib.

---

## 14. Podsumowanie

| Aspekt | Wartość |
|--------|---------|
| **Język** | Python 3.11+ |
| **Instalacja** | `pip install -e <path>` |
| **Entry point** | `tost` (CLI) lub `python -m tost` |
| **Źródło danych** | `~/.claude/projects/**/*.jsonl` (append-only) |
| **API keys** | ŻADNE (Claude Max user) — tylko Notion opcjonalnie |
| **Daemon'y** | `ping-collect` (co 5 min), `sync` (co 60s) |
| **TUI** | Textual — dashboard / cc / holmes / ping / thc |
| **State lokalny** | 3× SQLite (WAL) + cache WAV + marker sonar |
| **Sync Notion** | 5 osobnych baz (sesje / Taryfa / Suspects / Ping / THC) |
| **Kolory tier** | GREEN / YELLOW / ORANGE / RED (serwerowy) |
| **Kolory taryfa** | ZIELONA / ŻÓŁTA / POMARAŃCZOWA / CZERWONA |
