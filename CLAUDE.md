# TOST — Token Optimization System Tool

## Opis projektu

Narzędzie do monitorowania zużycia tokenów w Claude Code. Czyta bezpośrednio pliki JSONL z `~/.claude/projects/`, wyświetla sesje w TUI (identycznie jak w Notion) i synchronizuje je do bazy Notion.

## Architektura

Całość działa lokalnie. Żadnych API-keyów (użytkownik ma Claude Max, nie API). Wyłącznie Notion API do syncu (opcjonalny — moduły działają bez Notion).

```
 ┌─ DANE ŹRÓDŁOWE ────────────────────────────────────────────────────────┐
 │ ~/.claude/projects/**/*.jsonl     api.anthropic.com (HEAD bez klucza)  │
 └────────────────┬───────────────────────────────┬───────────────────────┘
                  │                               │
      ┌───────────┴───────────┐            ┌──────┴──────┐
      │                       │            │             │
      ▼                       ▼            ▼             │
 jsonl_scanner          taryfa.scan    ping.py           │
 (per session)          (per hour)     (5-min daemon)    │
      │                       │            │             │
      │                       │            │             │
 ┌────┴─────┐           ┌─────┴─────┐ ┌────┴─────┐  ┌────┴──────┐
 │ dashboard │          │ tost_     │ │ tost_    │  │ sound.py  │
 │  (TUI)    │          │ taryfa.db │ │ ping.db  │  │ (sonar)   │
 └────┬─────┘           └─────┬─────┘ └────┬─────┘  └───────────┘
      │                       │            │
      ▼                       ▼            ▼
 notion_sync            taryfa_notion    thc.py (TUI)
 (Notion: Sesje)        (Notion: Taryfa) ← (czyta wszystkie 3 SQLite)
      │                       │
      │             ┌─────────┴────────┐
      │             ▼                  ▼
      │        Server tier       Taryfa level
      │       GREEN/YEL/ORA/RED  ZIELONA/ZOLTA/POMARANCZOWA/CZERWONA
      │
 holmes.py (TUI) ─────> Notion: Suspects  (6 reguł anomalii sesji)
```

## Kluczowe moduły

| Moduł | Rola |
|-------|------|
| `dashboard.py` | TUI Textual — lista sesji (identyczna z Notion) |
| `jsonl_scanner.py` | Parser `~/.claude/projects/*.jsonl` → agregaty sesji |
| `notion_sync.py` | Upsert sesji do Notion DB (co 60s) |
| `cost.py` | Tabele cenowe Anthropic (Opus/Sonnet/Haiku) |
| `cli.py` | Entry point — subkomendy: `monitor` (domyślna), `sync`, `cc`, `holmes` |
| `cc_panel.py` | TUI: TOST + panel terminala Claude Code (cc) side-by-side |
| `holmes.py` | Silnik analizy anomalii tokenów — 6 reguł, zapis do Notion Suspects |
| `holmes_ui.py` | TUI Holmesa — wybór okresu, wyniki, push do Notion |
| `holmes_rules.toml` | Konfigurowalne progi reguł Holmesa (edytowalne bez kodu) |
| `ping.py` | Pomiar latency API Anthropic, zapis SQLite, sync do Notion (hourly + THC 15-min) |
| `ping_ui.py` | TUI podglądu latency (readonly viewer) |
| `thc.py` | THC — Traffic Hours Console (Matrix TUI): zegar+tiery, ping-panel, taryfa, 24h profil, recent log |
| `thc_tiers.py` | Strefy zagrożenia GREEN/YELLOW/ORANGE/RED + countdowny (next change / to RED) |
| `thc_tiers.toml` | Konfig godzin UTC → tier (edytowalne bez kodu) |
| `taryfa.py` | Burn-rate detektor tokenów: 7-dniowy baseline godziny doby + ratio + z-score (MAD) → ZIELONA/ŻÓŁTA/POMARAŃCZOWA/CZERWONA |
| `taryfa_notion.py` | Sync kubełków godzinowych do bazy Notion "Taryfa" (auto-create pod parent page) |
| `taryfa_thresholds.toml` | Progi ratio/z-score + długość baselinu (edytowalne bez kodu) |
| `sound.py` | Sonar — proceduralnie generowany WAV (log-sweep 800→440Hz), nieblokujące `winsound.PlaySound(SND_ASYNC)` po każdym pingu |

## Zmienne środowiskowe (cheat sheet)

Wszystko w `.env` w katalogu projektu. `tost-launcher.ps1` / `tost sync` / `ping-collect` same ładują plik.

| Var | Wymagana | Moduł | Opis |
|-----|----------|-------|------|
| `NOTION_TOKEN` | do syncu | wszystkie | Token integracji Notion (secret_...). Bez niej nic nie idzie do Notion, ale TUI działa. |
| `NOTION_DATABASE_ID` | do `tost sync` | sesje | Baza sesji CC — jeden rekord per session JSONL. ID: `6b9e6206ca1f4097b342d3ecdf11598b`. |
| `HOLMES_SUSPECTS_DB_ID` | do Holmes sync | holmes | Osobna baza na podejrzane sesje. Auto-create przez `_ensure_suspects_db()`. |
| `PING_NOTION_DB_ID` | opcjonalna | ping | Hourly aggregaty latency (30-min sync). Brak → tylko lokalny zapis w tost_ping.db. |
| `THC_NOTION_DB_ID` | opcjonalna | ping → THC | 15-min buckety z polem Tier. Sync co 15 min w `ping-collect`. |
| `TARYFA_NOTION_DB_ID` | jedna z dwóch | taryfa | Jeśli masz już utworzoną bazę "TOST Taryfa" — podaj jej ID. Ma priorytet nad parent_page_id. |
| `TARYFA_NOTION_PARENT_PAGE_ID` | jedna z dwóch | taryfa | Page ID strony-rodzica. Przy pierwszym sync baza auto-utworzy się pod tą stroną, jej ID trafi do cache w tost_taryfa.db. |

## Stan lokalny (SQLite + cache)

Wszystko w `~/.claude/`:

| Plik | Moduł | Zawartość |
|------|-------|-----------|
| `tost_notion.db` | notion_sync | file mtimes + session_id → page_id |
| `tost_ping.db` | ping | surowe pomiary latency + flagi synced (notion + thc) |
| `tost_taryfa.db` | taryfa | kubełki godzinowe + offsety JSONL + mapowanie Notion + cache database_id |
| `tost_sonar.wav` | sound | cache wygenerowanego proceduralnie WAV sonaru (~10 KB) |
| `tost_sonar_disabled` | sound | plik-marker: obecność = sonar OFF (brak = ON, default) |

## Pierwsze uruchomienie (setup checklist)

1. **Python 3.11+** zainstalowany. Sprawdź: `python --version`.
2. W katalogu projektu: `pip install -e .` (instaluje `tost` CLI + deps z pyproject.toml).
3. Utwórz `.env` z minimum `NOTION_TOKEN` + `NOTION_DATABASE_ID` (jeśli chcesz sync sesji).
4. Uruchom raz: `tost monitor` — dashboard pokaże Twoje sesje z `~/.claude/projects/`.
5. W tle: `tost sync` — ciągły sync sesji do Notion co 60s.
6. Oddzielny proces: `tost ping-collect` — daemon pomiaru latency co 5 min (+ sonar).
7. Podgląd: `tost thc` — Matrix TUI z tierami serwerowymi + Taryfą.
8. (Opcjonalnie) `tost holmes` — analiza anomalii sesji.
9. Skróty na pulpicie: `powershell -ExecutionPolicy Bypass -File create-shortcut-launcher.ps1` → `TOST Launcher.lnk` z menu wszystkich modułów.

## Wymagania

- Python 3.11+ (używamy `tomllib` stdlib, `dataclasses`, type hints PEP 604)
- Windows (sonar przez `winsound` — na macOS/Linux sonar po prostu nie gra, reszta działa)
- Textual ≥ 0.50 (TUI)
- aiohttp (async HTTP — Notion + ping)
- Claude Max (nie API key — żaden moduł NIE może wymagać `ANTHROPIC_API_KEY`)

## Holmes — analizator anomalii

- **Uruchomienie:** `tost holmes` (TUI) lub `tost holmes --no-tui`
- **Reguły:** `tost/holmes_rules.toml` — edytować progi bez dotykania kodu
- **Env var bazy Suspects:** `HOLMES_SUSPECTS_DB_ID` (fallback: `NOTION_DATABASE_ID`)
- Suspects to OSOBNA baza Notion — tworzona ręcznie lub przez `_ensure_suspects_db()`
- **Skrót:** `create-shortcut-holmes.ps1`
- 6 reguł: `cache_invalidation`, `long_session_overflow`, `think_mode_waste`, `mcp_overload`, `session_cost_spike`, `high_cache_creation`

## Ping — monitoring latency API Anthropic

- **Kolektor:** `tost ping-collect` (daemon, co 5 min)
- **Podgląd:** `tost ping` (TUI, readonly)
- **Env var:** `PING_NOTION_DB_ID` (opcjonalny, do sync Notion hourly)
- **Env var:** `THC_NOTION_DB_ID` (opcjonalny, 15-min agregaty dla THC)
- **State:** `~/.claude/tost_ping.db` (SQLite, WAL mode)
- **Endpoint:** HEAD api.anthropic.com + status.anthropic.com (bez API key)
- **Notion sync:** hourly co 30 min, THC 15-min co 15 min (niezależne flagi synced)
- Dashboard TOST pokazuje bieżący ping w SummaryBar
- **Sonar po pingu:** `tost/sound.py` — delikatny log-sweep 800→440 Hz (~220 ms), `winsound.PlaySound(SND_ASYNC)`. Domyślnie ON; toggle z THC TUI klawiszem `s`. Plik-marker: `~/.claude/tost_sonar_disabled` (obecność = OFF). WAV cache: `~/.claude/tost_sonar.wav`. Gra tylko dla targetu `api` (nie duplikuje na parę api+status).

## Taryfa — burn-rate tokenów

- **Silnik:** `tost/taryfa.py` — inkrementalny skan JSONL po byte-offset → kubełki (date, hour UTC).
- **Algorytm:** porównuje `tokens_so_far` vs `median × elapsed_fraction` dla tej samej godziny doby z ostatnich 7 dni. Sygnały: `ratio` + `z-score` (MAD-based, 1.4826 × MAD ≈ stdev). Taryfa = MAX severity z (ratio-thresh, z-thresh, p90-multiplier).
- **Poziomy:** ZIELONA / ŻÓŁTA / POMARAŃCZOWA / CZERWONA (same kolory co tiery serwerowe — ale niezależny sygnał).
- **Fallback:** < 5 próbek w baselinie per hour → all-day median z 7 dni; < 5 globalnie → ZIELONA. `min_elapsed_seconds=120` żeby nie straszyć ratio na początku godziny.
- **Progi:** `tost/taryfa_thresholds.toml` — edytować bez kodu, reload w THC przez `Ctrl+R`.
- **State:** `~/.claude/tost_taryfa.db` (SQLite WAL) — kubełki + offsety plików JSONL + mapowanie Notion.
- **Widget THC:** panel pod top-rowem (height 5): label taryfy, ratio, z-score, tokens_so_far/baseline/projected, cumulative dzisiaj, koszt, mini-sparkline 24h godzin tego dnia, stan sonaru.
- **Notion DB "Taryfa":** auto-create pod `TARYFA_NOTION_PARENT_PAGE_ID` (jeśli brak `TARYFA_NOTION_DB_ID`). Pola: Slot/Date/Hour/Tokens/Cost USD/Baseline median/p90/samples/Burn ratio/Z-score/Tariff/Server tier/Synced at. Sync co 15 min w `tost sync` (lookback 2 dni, upsert po (date, hour)).

## THC — Traffic Hours Console

- **Uruchomienie:** `tost thc` (Matrix TUI, read-only z tost_ping.db)
- **Skrót:** `create-shortcut-thc.ps1` → `THC.lnk` na pulpicie
- **Tiery:** GREEN (USA śpi) / YELLOW / ORANGE / RED (peak US East+West overlap) — weekendy zawsze GREEN
- **Progi:** `tost/thc_tiers.toml` (godzina UTC → tier) — edytować bez kodu, reload w appie przez `Ctrl+R`
- **Widgety:** Clock (UTC+lokalny, tier, 2 countdowny next/to-RED), PingPanel (now/1h/24h), TierStats (avg TTFB per tier 7d), **Taryfa** (burn-rate tokenów + sonar toggle), 24hHistogram (bar-chart UTC z barwami tierów), RecentLog
- **Notion DB (osobna):** `THC_NOTION_DB_ID` — 15-min buckety z polami Date/Hour/Minute/Target/Tier/Avg TTFB/Avg Total/Sample Count/Error Count
- **Paleta:** Matrix (`#001100` tło, `#39FF14` akcent) — zgodna ze stylem projektu MTX
- **Klawisze:** `q` wyjście, `r` odśwież, `Ctrl+R` reload TOML (tiery + taryfa), `s` toggle sonaru

## Konwencje

- CLI entry point: `tost.cli:main`, subkomendy: `monitor` (domyślna), `sync`, `cc`, `holmes`, `ping`, `ping-collect`, `thc`
- **Unified launcher:** `tost-launcher.ps1` + `create-shortcut-launcher.ps1` → `TOST Launcher.lnk` (jedno menu: TOST / CC / Holmes / Ping / THC, z podmenu i pętlą powrotu)
- Skróty pojedyncze (opcjonalne, szybki dostęp): `create-shortcut.ps1` (TOST), `create-shortcut-notion-sync.ps1` (Notion Sync), `create-shortcut-cc.ps1` (TOST+CC), `create-shortcut-holmes.ps1` (Holmes), `create-shortcut-thc.ps1` (THC)
- Dashboard w Textual, odświeżanie co 15s
- Koszt liczony z `tost.cost.calculate_cost()`
- Stan Notion sync: `~/.claude/tost_notion.db`

## Środowisko i gotcha

- `python -m tost.cli` nie daje outputu — używaj `python -m tost <subkomenda>` lub `tost <subkomenda>`
- Windows Startup autostart: skrót `.lnk` w `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` — nie wymaga admina; `schtasks /SC ONLOGON` i `Register-ScheduledTask` wymagają admina
- `schtasks` przez Git Bash traktuje `/` jako ścieżkę — zawsze wywołuj przez `powershell -Command "schtasks ..."`
- SQLite migracja: przy dodawaniu kolumn sprawdzaj `PRAGMA table_info(ping_raw)` — używaj osobnego `ADDABLE_COLUMNS` i zawsze dodawaj brakujące kolumny niezależnie od wersji schematu
- `aiohttp.TraceConfig` nie rozdziela TCP i TLS — `on_connection_create` obejmuje oba; TTFB = `request_end - request_start`
- Użytkownik ma Claude Max (nie API key) — żadne funkcje nie mogą wymagać `ANTHROPIC_API_KEY`
- `ping.py` tworzy nową sesję `aiohttp` per pomiar (nie reużywa session pool) — wymagane żeby mierzyć pełny DNS+Connect+TTFB
