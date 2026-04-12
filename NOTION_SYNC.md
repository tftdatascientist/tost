# TOST Notion Sync

Synchronizuje dane sesji Claude Code z bazy `~/.claude/projects/*.jsonl` do Notion. Jedna strona na sesję, aktualizowana in-place.

## Uruchomienie

### CLI

```bash
# Ciągły sync co 60s
tost sync

# Jednorazowy pass
tost sync --once -v

# Zmieniony interwał
tost sync --interval 30
```

### Standalone (bez CLI tost)

```bash
python -m tost.notion_sync
python -m tost.notion_sync --once -v
python -m tost.notion_sync --interval 30
```

### Z innego programu (Python API)

```python
import asyncio
from tost.notion_sync import NotionConfig, run_sync_loop, DEFAULT_STATE_DB

cfg = NotionConfig(
    token="secret_xxx",              # lub ntn_xxx
    database_id="6b9e6206...",       # 32-char hex
    interval=60.0,                   # sekundy między passami
    title_property="Session",        # nazwa kolumny title w Notion
)

# Jednorazowy pass
asyncio.run(run_sync_loop(cfg, state_db=DEFAULT_STATE_DB, once=True))

# Ciągły loop (blokujący)
asyncio.run(run_sync_loop(cfg))
```

### Z innego programu (subprocess)

```bash
# Env vars muszą być ustawione
NOTION_TOKEN=secret_xxx NOTION_DATABASE_ID=6b9e6206... python -m tost.notion_sync --once
```

Exit code: `0` = sukces, `1` = brak tokena/database ID.

## Konfiguracja

### Zmienne środowiskowe (wymagane)

| Zmienna | Opis |
|---------|------|
| `NOTION_TOKEN` | Token integracji Notion (`secret_...` lub `ntn_...`) |
| `NOTION_DATABASE_ID` | ID bazy danych Notion (32-char hex) |

Obsługiwane też przez `.env` w katalogu roboczym (automatyczny `load_dotenv`).

### Argumenty CLI

| Argument | Domyślna | Opis |
|----------|----------|------|
| `--once` | false | Jeden pass i wyjdź |
| `--interval N` | 60 | Interwał w sekundach |
| `--verbose` / `-v` | false | Logi DEBUG |
| `--token` | env | Token (tylko `python -m tost.notion_sync`) |
| `--database-id` | env | Database ID (tylko `python -m tost.notion_sync`) |
| `--state-db` | `~/.claude/tost_notion.db` | Ścieżka do pliku stanu |
| `--title-property` | `Session` | Nazwa kolumny title w Notion |

## Schemat bazy Notion

Nazwy właściwości są case-sensitive. Wszystkie muszą istnieć:

| Właściwość | Typ | Opis |
|------------|-----|------|
| `Session` | Title | Tytuł strony (`projekt · id[:8]`) |
| `Session ID` | Text | Klucz upsert — UUID sesji |
| `Project` | Text | Zdekodowana ścieżka projektu |
| `Model` | Select | Główny model sesji |
| `Started` | Date | Najwcześniejsza wiadomość |
| `Last message` | Date | Najnowsza wiadomość |
| `Messages` | Number | Liczba wiadomości asystenta |
| `Input tokens` | Number | |
| `Output tokens` | Number | |
| `Cache read` | Number | |
| `Cache create` | Number | |
| `Cost USD` | Number (USD) | Koszt z `tost.cost` |

**Database ID:** `6b9e6206ca1f4097b342d3ecdf11598b`

## Jak działa

1. **Scanner** (`jsonl_scanner.py`) — czyta `~/.claude/projects/<encoded-cwd>/*.jsonl`, parsuje rekordy `type=="assistant"`, sumuje `message.usage`
2. **State** (`~/.claude/tost_notion.db`) — SQLite z mtimes plików i mapowaniem `session_id → page_id`. Restart-safe, bez duplikatów
3. **Pierwszy run** — odpytuje Notion DB żeby zbudować mapping istniejących stron
4. **Kolejne passy** — skanuje tylko pliki z nowym mtime. PATCH jeśli strona istnieje, POST jeśli nie
5. Pliki >100 MB są pomijane

## Struktura kodu

| Plik | Rola |
|------|------|
| `tost/notion_sync.py` | Klient Notion + sync loop + CLI standalone |
| `tost/jsonl_scanner.py` | Parser JSONL → `SessionAggregate` |
| `tost/cost.py` | Tabele cenowe Anthropic |

### Kluczowe klasy i funkcje

```
NotionConfig(token, database_id, interval, title_property)  — konfiguracja
NotionSyncState(db_path)     — persystencja stanu w SQLite
NotionClient(cfg)            — HTTP do Notion API
run_sync_loop(cfg, state_db, once)  — główna pętla async

SessionAggregate             — dataclass z agregatem sesji
get_changed_sessions(since_mtime)   — generator zmienionych sesji
scan_session_file(path)      — agregat pojedynczego pliku
scan_all_sessions()          — pełny skan (bez filtrowania po mtime)
```
