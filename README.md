# TOST — Token Optimization System Tool

Monitorowanie zużycia tokenów w Claude Code (plan Max, bez API key).
Czyta pliki JSONL z `~/.claude/projects/`, agreguje sesje, wizualizuje
burn-rate, mierzy latency API i (opcjonalnie) synchronizuje wszystko
do Notion.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Co robi

TOST to zestaw niezależnych modułów wokół jednego źródła prawdy —
plików JSONL, które Claude Code zapisuje lokalnie dla każdej sesji.

- **Dashboard sesji** (`tost monitor`) — lista sesji w TUI, tokeny,
  koszt, ostatnia aktywność.
- **CC panel** (`tost cc`) — TOST + terminal Claude Code obok siebie.
- **Holmes** (`tost holmes`) — analiza anomalii sesji (6 reguł:
  cache invalidation, overflow, think waste, MCP overload, cost
  spike, cache creation), zapis do osobnej bazy Notion.
- **Ping** (`tost ping-collect` + `tost ping`) — daemon mierzący
  latency api.anthropic.com i status.anthropic.com co 5 minut;
  po każdym pomiarze gra delikatny sonar.
- **THC — Traffic Hours Console** (`tost thc`) — Matrix TUI z zegarem
  UTC, tierami serwerowymi (GREEN/YELLOW/ORANGE/RED), panelem ping,
  histogramem 24h i panelem **Taryfa**.
- **Taryfa** — burn-rate detektor tokenów: porównuje bieżącą godzinę
  z 7-dniową medianą tej samej godziny doby (ratio + z-score MAD),
  sygnalizuje ZIELONA / ŻÓŁTA / POMARAŃCZOWA / CZERWONA. Syncuje
  kubełki godzinowe do bazy Notion (auto-create).
- **Notion sync** (`tost sync`) — upsert sesji + taryfy do Notion
  (opcjonalne; moduły działają bez Notion).

## Architektura

```
~/.claude/projects/**/*.jsonl        api.anthropic.com (HEAD)
         │                                 │
         ▼                                 ▼
    jsonl_scanner                      ping.py (5 min)
    taryfa.scan                        └─► tost_ping.db
         │
         ├─► tost_taryfa.db ─► taryfa_notion ─► Notion: Taryfa
         │
         └─► dashboard / holmes / cc_panel
                 │
                 ├─► notion_sync ─► Notion: Sesje
                 └─► holmes ─► Notion: Suspects

    thc.py (Matrix TUI) ← czyta wszystkie 3 SQLite + TOML tiery
                          + sonar toggle
```

Żaden moduł nie wymaga `ANTHROPIC_API_KEY` — TOST to narzędzie dla
użytkowników planu Claude Max.

## Instalacja

```bash
git clone https://github.com/tftdatascientist/tost.git
cd tost
pip install -e .
```

**Wymagania:** Python 3.11+ (używamy `tomllib` z stdlib).
Windows dla sonaru (`winsound`); na macOS/Linux sonar po prostu
nie gra, reszta działa.

## Szybki start

```bash
tost monitor          # dashboard sesji (default)
tost cc               # TOST + terminal CC
tost holmes           # analizator anomalii
tost ping-collect     # daemon latency (w tle, 5 min)
tost ping             # viewer latency
tost thc              # Matrix TUI — tiery + taryfa
tost sync             # Notion sync (sesje + taryfa)
```

## Konfiguracja Notion (opcjonalna)

Utwórz `.env` w katalogu projektu:

```
NOTION_TOKEN=secret_xxx...
NOTION_DATABASE_ID=6b9e6206ca1f4097b342d3ecdf11598b

# Opcjonalne:
HOLMES_SUSPECTS_DB_ID=...
PING_NOTION_DB_ID=...
THC_NOTION_DB_ID=...
TARYFA_NOTION_DB_ID=...
# ALBO (auto-create bazy Taryfa pod stroną):
TARYFA_NOTION_PARENT_PAGE_ID=...
```

Pełna tabela zmiennych: zobacz `CLAUDE.md` sekcja *Zmienne
środowiskowe*.

## Windows — launcher na pulpicie

Pojedynczy skrót z menu wszystkich modułów:

```powershell
powershell -ExecutionPolicy Bypass -File create-shortcut-launcher.ps1
```

Tworzy `TOST Launcher.lnk` na pulpicie → menu: TOST / CC / Holmes /
Ping / THC z powrotem do menu po zamknięciu modułu.

Dostępne są też pojedyncze skróty (szybki dostęp do jednego modułu):
`create-shortcut.ps1`, `create-shortcut-cc.ps1`,
`create-shortcut-holmes.ps1`, `create-shortcut-thc.ps1`,
`create-shortcut-ping.ps1`, `create-shortcut-notion-sync.ps1`.

## Stan lokalny

Wszystkie bazy w `~/.claude/`:

| Plik | Zawartość |
|------|-----------|
| `tost_notion.db` | mtimes plików + session_id → Notion page_id |
| `tost_ping.db` | surowe pomiary latency + flagi sync |
| `tost_taryfa.db` | kubełki godzinowe + offsety JSONL + cache DB id |
| `tost_sonar.wav` | cache proceduralnie generowanego WAV sonaru |
| `tost_sonar_disabled` | marker: obecność = sonar OFF |

## Konfigurowalne progi (TOML — edytowalne bez kodu)

- `tost/holmes_rules.toml` — progi 6 reguł Holmesa
- `tost/thc_tiers.toml` — mapowanie godzina UTC → tier
- `tost/taryfa_thresholds.toml` — ratio/z-score dla taryfy

W THC TUI reload progów: `Ctrl+R`.

## Klawisze

### Dashboard (`tost monitor`)
`q` wyjście, `r` refresh

### Holmes TUI (`tost holmes`)
`q` wyjście, `Enter` analiza, `s` push do Notion

### Ping viewer (`tost ping`)
`q` wyjście, `r` refresh

### THC (`tost thc`)
`q` wyjście, `r` refresh, `Ctrl+R` reload TOML (tiery + taryfa),
`s` toggle sonaru

## Ceny (Anthropic)

Wbudowane tabele cenowe (per 1M tokenów):

| Model | Input | Output | Cache Read | Cache Creation |
|-------|-------|--------|------------|----------------|
| Opus 4 | $15.00 | $75.00 | $1.50 | $18.75 |
| Sonnet 4 | $3.00 | $15.00 | $0.30 | $3.75 |
| Haiku 4 | $0.80 | $4.00 | $0.08 | $1.00 |

## Struktura projektu

```
tost/
  cli.py                  # entry point — subkomendy
  dashboard.py            # TUI — lista sesji
  cc_panel.py             # TUI — TOST + terminal CC
  jsonl_scanner.py        # parser ~/.claude/projects/*.jsonl
  notion_sync.py          # upsert sesji + taryfy do Notion
  cost.py                 # tabele cenowe Anthropic
  holmes.py               # silnik analizy anomalii (6 reguł)
  holmes_ui.py            # TUI Holmesa
  holmes_rules.toml       # progi reguł
  ping.py                 # daemon latency + sonar trigger
  ping_ui.py              # viewer latency
  thc.py                  # Matrix TUI — tiery + taryfa
  thc_tiers.py            # logika tierów GREEN..RED
  thc_tiers.toml          # godzina UTC → tier
  taryfa.py               # burn-rate detektor (7d baseline)
  taryfa_notion.py        # sync kubełków do Notion (auto-create)
  taryfa_thresholds.toml  # progi ratio/z-score
  sound.py                # sonar (WAV + winsound.PlaySound)
```

## Licencja

MIT
