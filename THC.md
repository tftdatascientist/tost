# THC — Traffic Hours Console

Matrix-style TUI (Textual) do monitorowania presji na limity Claude Max w czasie rzeczywistym. Łączy trzy niezależne sygnały: **godzinę doby** (tier serwerowy), **latency API** (ping 1h) i **burn-rate tokenów** (taryfa).

Uruchomienie: `tost thc`
Skrót: `create-shortcut-thc.ps1` → `THC.lnk` na pulpicie
Tryb: read-only (dane bierze ze stanu zapisanego przez `tost ping-collect` i skanera JSONL)
Odświeżanie: co 5 sekund

---

## 1. Layout okna

```
┌───────────────────────────────────────────────────────────────────────┐
│  THC — TRAFFIC HOURS CONSOLE                                          │ Header
├─────────────────────────────┬──────────────┬──────────────────────────┤
│ ◈ CLOCK  CET                │ ◈ PING       │ ◈ TIER STATS  7d         │
│                             │ api.anth...  │                          │
│   13:45:22  (duże cyfry)    │ NOW  TTFB …  │ ● GREEN  TTFB … ms       │ top-row (14)
│   CEST  pon 17 kwi 2026     │ 1h   TTFB …  │ ● YELLOW …               │
│   UTC 11:45:22              │ 24h  TTFB …  │ ● ORANGE …               │
│   TIER ● YELLOW  NEXT …     │              │ ● RED …                  │
│   ┌ US EAST ─┬ US WEST ─┐   │              │                          │
│   │ 07:45:22 │ 04:45:22 │   │              │                          │
│   └──────────┴──────────┘   │              │                          │
├─────────────────────────────┴──────────────┴──────────────────────────┤
│ ◈ NACISK NA LIMITY  godzina · ping 1h · burn-rate                     │
│ ┌─ GODZINA ────┐ ┌─ PING 1h ────┐ ┌─ BURN TOKENOW ──┐                 │ taryfa (12)
│ │ ███ YELLOW ██│ │ ███ GREEN ██ │ │ ███ ZIELONA ███ │                 │
│ │ UTC 11:00    │ │ 312 ms TTFB  │ │ ratio 0.8× z-0.2│                 │
│ └──────────────┘ └──────────────┘ └─────────────────┘                 │
│ teraz 42k / base 55k  proj 98k  dzis 1.2M $4.80  sonar ● (s)          │
│ ▂▁▂▃▄▅▇█▆▄▃▂▁ ... (sparkline 24h)                                     │
├───────────────────────────────────────────────────────────────────────┤
│ ◈ 24H PROFIL — avg TTFB per godzina UTC — ostatnie 7 dni              │ hist (auto)
│ 00    03    06    09    12    15    18    21                          │
│ ▁ ▁ ▁ ▁ ▂ ▃ ▃ ▄ ▅ ▆ ▇ █ █ ▇ ▅ ▃ ▂ ▁ ▁ ▁ ▁ ▁ ▁ ▁                        │
│ ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ● ●                       │
├───────────────────────────────────────────────────────────────────────┤
│ ◈ RECENT PINGS (DataTable 50 wierszy)                                 │ recent (1fr)
└───────────────────────────────────────────────────────────────────────┘
```

Wysokości (CSS `tost/thc.py` → `ThcApp.CSS`):
- `#top-row` = 14
- `#taryfa-box` = 12
- `#hist-box` = auto (~7 rzędów)
- `#recent-log` = 1fr (reszta okna)

---

## 2. Klawisze

| Klawisz | Akcja |
|---------|-------|
| `q` | Wyjście |
| `r` | Ręczne odświeżenie (poza auto-refresh co 5s) |
| `Ctrl+R` | Reload TOML-i (tiery + progi taryfy) bez restartu appa |
| `s` | Toggle sonaru (dźwiękowy sygnał po pingu) |

---

## 3. Widżety — szczegóły

### 3.1 ThcClock — duży zegar CET + info + 2 małe zegary USA

Panel wielokolumnowy (2fr vs ping/tier 1fr każdy):

**Główny zegar (Textual `Digits`)** — duże cyfry, strefa `Europe/Warsaw` (CET zimą, CEST latem, przełączanie automatyczne przez `zoneinfo`).

**Info row** — 3 linie:
- Linia 1: skrót strefy (CET/CEST) + data (`pon 17 kwi 2026`) + czas UTC
- Linia 2: `TIER ● <kolor>` + `NEXT <kolor>` + countdown do zmiany (HH:MM:SS)
- Linia 3: jeśli jesteśmy w RED → `● RED ACTIVE ends in HH:MM:SS`, w przeciwnym razie → `RED in HH:MM:SS (Dzień HH:MM UTC)`

**US Clocks row** — 2 boxy obok siebie:
- `US EAST` = `America/New_York` (EST/EDT, przełączanie DST automatyczne)
- `US WEST` = `America/Los_Angeles` (PST/PDT, przełączanie DST automatyczne)
- Każdy pokazuje HH:MM:SS + skrót strefy + datę skróconą

Fallback gdy brak `tzdata` (Windows bez pakietu): sztywne offsety CET=+01, EST=−05, PST=−08 **bez DST** — latem będą wyświetlać złą godzinę. Zależność `tzdata>=2024.1` jest w `pyproject.toml` warunkowo dla Windows, więc normalnie DST działa.

### 3.2 ThcPingPanel — bieżąca latencja API

Target: `api.anthropic.com` (HEAD bez klucza API).

Pola:
- `NOW` — ostatni pomiar: TTFB, Total, tier serwerowy w chwili pomiaru (`●`)
- `1h` — rolling średnia z 60 minut: TTFB, Total, liczba prób
- `24h` — daily average: TTFB, Total, liczba prób + licznik błędów

Źródło: `~/.claude/tost_ping.db`. Brak bazy → komunikat "uruchom `tost ping-collect`".

### 3.3 ThcTierStats — średnie TTFB per tier (7 dni)

Agregaty ważone liczbą próbek. Dla każdego z 4 tierów:
```
● GREEN   TTFB   412 ms  (2847 prób)
● YELLOW  TTFB   586 ms  ( 891 prób)
● ORANGE  TTFB   743 ms  ( 412 prób)
● RED     TTFB  1203 ms  (1008 prób)
```

Źródło: `PingState.get_hourly_summary(days=7, target="api")`, mapowanie godziny UTC → tier przez `schedule_for_hour_range(weekend=False)`.

### 3.4 ThcTaryfaPanel — NACISK NA LIMITY (3 kolorowe wskaźniki)

**To jest centralny widżet** — pokazuje **3 niezależne warstwy** sygnalizujące że Twoje limity Claude Max są prawdopodobnie pod presją:

| Warstwa | Co mierzy | Źródło | Paleta |
|---------|-----------|--------|--------|
| **GODZINA** | Jak bardzo serwer Anthropic jest obciążony w tej porze doby (statycznie wg harmonogramu) | `thc_tiers.toml` + aktualna godzina UTC | GREEN/YELLOW/ORANGE/RED |
| **PING 1h** | Średnia latencja API w ostatniej godzinie — proxy dla aktualnego obciążenia serwerów | `tost_ping.db` rolling 60 min | GREEN/YELLOW/ORANGE/RED |
| **BURN TOKENOW** | Tempo zużycia tokenów vs. 7-dniowy baseline tej godziny doby | `tost_taryfa.db` + algorytm taryfy | ZIELONA/ZOLTA/POMARANCZOWA/CZERWONA |

Każdy wskaźnik to kolorowy blok `███ <LABEL> ███` + krótki detail-line. Gdy któraś warstwa skacze wysoko — rozważ ograniczenie intensywności sesji CC.

Pod wskaźnikami:
- Linia szczegółów taryfy: tokeny teraz / baseline / projekcja / cumulative dziś / koszt / stan sonaru
- Sparkline 24h: 24 barki z tokenami per godzina tego dnia, bieżąca godzina pokolorowana kolorem taryfy

### 3.5 Thc24hHistogram — profil godzinowy avg TTFB

Dla każdej godziny UTC (0–23) pokazuje wysokość słupka proporcjonalną do średniego TTFB z ostatnich 7 dni. Kolory słupków = tier dla tej godziny. Pod słupkami linia kropek `●` z tymi samymi kolorami (legenda tierów).

Podpis: `skala: max XXX ms   bieżący tier: ● <kolor>`.

### 3.6 ThcRecentLog — DataTable z ostatnimi 50 pingami

Kolumny: `Czas UTC | Target | Tier | TTFB | Connect | DNS | Total | Status | Błąd`. Tier koloruje się per-wiersz wg godziny pomiaru.

---

## 4. Algorytm Taryfy — jak obliczane jest "badanie"

Kod: `tost/taryfa.py` → `compute_tariff(state, now, thresholds)`.

### 4.1 Model danych

Wszystkie sesje Claude Code zostawiają `.jsonl` w `~/.claude/projects/<workspace>/`. Każda linia assistant-message ma pole `usage` (input/output/cache). `scan_new_records()` czyta inkrementalnie (byte-offset zapamiętany w `taryfa_file_offsets`) i agreguje do kubełków godzinowych:

```
taryfa_hourly (date, hour UTC) → input_tokens, output_tokens,
                                 cache_read_tokens, cache_creation_tokens,
                                 cost_usd, message_count
```

`total_tokens = input + output + cache_read + cache_creation` — sumuje wszystkie 4 kategorie.

### 4.2 Bieżąca chwila

Dla bieżącej godziny H dnia D:
```
tokens_so_far   = suma total_tokens w kubełku (D, H)
elapsed_sec     = now.minute*60 + now.second
elapsed_fraction= max(elapsed_sec / 3600, 1/3600)   # >= 1s, nigdy 0
```

### 4.3 Baseline

Bierze totale tokenów **z tej samej godziny H** z ostatnich `baseline_days` dni (domyślnie 7), pomijając dzisiaj. Z tego liczy:

```
median      = mediana(baseline)
MAD         = mediana(|x - median|)                 # Median Absolute Deviation
mad_scaled  = 1.4826 × MAD  (≈ stdev dla rozkładu normalnego)
p75, p90    = percentyle 75 i 90 baselinu
```

MAD jest używany zamiast klasycznego stdev bo jest **odporny na outliery** — jeden dzień ze skokiem nie psuje baselinu.

Gdy `mad = 0` (wszystkie wartości identyczne) — bierzemy `max(median × 0.1, 1.0)` żeby nie dzielić przez zero.

**Fallback 1:** jeśli < `min_samples` (domyślnie 5) próbek dla tej godziny H → baseline = **wszystkie godziny z ostatnich 7 dni** (`baseline_used = "all-day-fallback"`).

**Fallback 2:** jeśli nadal < 5 próbek globalnie → zwraca `Taryfa.GREEN` z `baseline_used = "insufficient"` (panel pokazuje "zbieram dane").

### 4.4 Dwa sygnały + p90-guard

```
expected_so_far = median × elapsed_fraction
ratio           = tokens_so_far / expected_so_far

projected       = tokens_so_far / elapsed_fraction       # ekstrapolacja do pełnej godziny
z_score         = (projected - median) / mad_scaled
```

- **Ratio** — ile razy przekraczasz typowe tempo (1.0 = norma, 2.0 = dwa razy szybciej).
- **Z-score** — jak daleko jesteś od mediany w jednostkach "MAD-stdev" (wyłapuje rzadkie skoki poza ogonem rozkładu).
- **p90-guard** — dodatkowy warunek CZERWONEJ: `projected > p90_multiplier_red × p90`. Wyłapuje sytuacje gdy MAD jest mały (stabilny baseline), ale jednorazowo projekcja przebije 90-ty percentyl razy 2.

### 4.5 Mapowanie na taryfę

Z ratio:
```
ratio <= green_ratio_max (1.0)   → ZIELONA
       <= yellow_ratio_max (1.5) → ZOLTA
       <= orange_ratio_max (2.5) → POMARANCZOWA
       > 2.5                     → CZERWONA
```

Z z-score:
```
z <= green_z_max (1.0)   → ZIELONA
  <= yellow_z_max (2.0)  → ZOLTA
  <= orange_z_max (3.0)  → POMARANCZOWA
  > 3.0                  → CZERWONA
```

Z p90-guard (tylko jeśli projected > p90_multiplier_red × p90): → CZERWONA.

**Wynik:** `taryfa = MAX severity` z trzech powyższych (po severity: GREEN=0, YELLOW=1, ORANGE=2, RED=3).

### 4.6 Ochrona przed fałszywymi alarmami

Gdy `elapsed_sec < min_elapsed_seconds` (domyślnie 120s) — zwraca **wymuszoną ZIELONĄ** bez liczenia sygnałów. Powód: 100 tokenów w pierwszej minucie godziny → projekcja 6000/h → fałszywy RED. Czekamy aż uzbiera się statystyka.

### 4.7 Progi — gdzie edytować

Plik: **`tost/taryfa_thresholds.toml`**. Parsing: `load_thresholds()`. Reload w THC TUI: **`Ctrl+R`** (bez restartu).

| Klucz | Default | Znaczenie |
|-------|---------|-----------|
| `baseline_days` | 7 | Ile dni wstecz do baselinu (bez dzisiaj) |
| `min_samples` | 5 | Minimum próbek; mniej → all-day fallback → "insufficient" |
| `green_ratio_max` | 1.0 | ratio ≤ tyle → ZIELONA |
| `yellow_ratio_max` | 1.5 | ratio ≤ tyle → ZOLTA |
| `orange_ratio_max` | 2.5 | ratio ≤ tyle → POMARANCZOWA (wyżej CZERWONA) |
| `green_z_max` | 1.0 | z ≤ tyle → ZIELONA |
| `yellow_z_max` | 2.0 | z ≤ tyle → ZOLTA |
| `orange_z_max` | 3.0 | z ≤ tyle → POMARANCZOWA (wyżej CZERWONA) |
| `p90_multiplier_red` | 2.0 | projected > tyle × p90 → wymusza CZERWONĄ |
| `min_elapsed_seconds` | 120 | Pierwsze X sekund godziny → zawsze ZIELONA |

---

## 5. Progi wskaźnika PING 1h

Kod: `tost/thc.py` → `_ping_pressure_level(avg_ttfb_ms)`. Progi są **hardkodowane** (nie w TOML):

| Avg TTFB rolling 1h | Poziom | Kolor (wspólny z tierami) |
|---------------------|--------|---------------------------|
| 0 (brak danych) | `BRAK` | szary (`#004400`) |
| < 500 ms | `GREEN` | `#39FF14` |
| 500–999 ms | `YELLOW` | `#FFD700` |
| 1000–1999 ms | `ORANGE` | `#FF8800` |
| ≥ 2000 ms | `RED` | `#FF3030` |

Zmiana progów: edycja `_ping_pressure_level()` w `tost/thc.py`. Nie ma TOML-a.

---

## 6. Tier serwerowy — harmonogram godzin UTC

Kod: `tost/thc_tiers.py`. Plik konfiguracyjny: **`tost/thc_tiers.toml`**. Reload: **`Ctrl+R`**.

### 6.1 Reguły

- **Weekendy (Sat+Sun)** → zawsze `GREEN` (hardcoded w `_is_weekend()`, nie konfigurowalne). Zgodne z oficjalnym off-peak window Anthropic (cały weekend = limity podwojone).
- **Weekdays** → mapowanie `hour UTC → tier` z TOML-a, fallback na `DEFAULT_WEEKDAY_SCHEDULE`.

### 6.2 Harmonogram oparty na oficjalnych peak hours Anthropic

**Źródło:** ogłoszenia Anthropic z marca 2026 ws. zarządzania pojemnością. Peak window dla Claude Code / Claude Max: **poniedziałek–piątek, 8:00 AM – 2:00 PM Eastern Time** (6 godzin). W peak limity sesji topnieją ~2× szybciej; poza peak (off-peak) + weekend → limity **podwojone**.

Konwersja na UTC z uwzględnieniem DST:
- **EDT** (marzec–listopad, lato): 12:00–17:59 UTC
- **EST** (listopad–marzec, zima): 13:00–18:59 UTC

Mapowanie robusne względem zmiany DST (bez potrzeby rekonfiguracji 2×/rok):

| UTC | PL (CEST) | Tier | Uzasadnienie |
|-----|-----------|------|--------------|
| 00–10 | 02–12 | GREEN | Off-peak wg Anthropic |
| 11 | 13 | YELLOW | Shoulder — godzina przed peak |
| 12 | 14 | ORANGE | Peak w EDT (lato), shoulder w EST |
| **13–17** | **15–19** | **RED** | Core peak w obu reżimach DST |
| 18 | 20 | ORANGE | Peak w EST (zima), shoulder w EDT |
| 19 | 21 | YELLOW | Shoulder — godzina po peak |
| 20–23 | 22–01 | GREEN | Off-peak (po 2 PM ET limity podwojone) |

Referencja godzinowa (kwiecień 2026, EDT/CEST):
```
UTC 11:00 = PL 13:00 = NYC 07:00 = LA 04:00   ← shoulder pre-peak
UTC 12:00 = PL 14:00 = NYC 08:00 = LA 05:00   ← peak start (EDT)
UTC 13:00 = PL 15:00 = NYC 09:00 = LA 06:00   ← core RED start
UTC 17:00 = PL 19:00 = NYC 13:00 = LA 10:00   ← core RED end
UTC 18:00 = PL 20:00 = NYC 14:00 = LA 11:00   ← peak end (EDT)
UTC 19:00 = PL 21:00 = NYC 15:00 = LA 12:00   ← shoulder post-peak
```

### 6.3 Dystrybucja tierów w dobie

| Tier | Liczba godzin | % doby |
|------|---------------|--------|
| RED | 5 | 21% |
| ORANGE | 2 | 8% |
| YELLOW | 2 | 8% |
| GREEN | 15 | 63% |

Weekendy: 24h GREEN (100%), zgodnie z off-peak window Anthropic.

### 6.4 Dlaczego nie na podstawie własnych pomiarów?

Eksperymentalnie próbowaliśmy oprzeć tiery na lokalnym pingu TTFB, ale:
- Anthropic nie zwraca `429 Too Many Requests` na pingi HEAD (zwraca 405) — brak bezpośredniego sygnału throttlingu
- TTFB (180–310 ms) waha się za słabo żeby wiarygodnie klasyfikować godziny
- Własne `burn-rate tokenów` pokazuje *kiedy ja pracuję*, a nie *kiedy serwer jest obciążony*

Oficjalny harmonogram Anthropic jest najlepszym źródłem, bo oni mają wgląd w globalny load. Tu go tylko odwzorowujemy.

Edycja: TOML `[weekday]` → pary `H = "TIER"` dla godzin 0–23. Nieprawidłowe wartości → fallback GREEN.

### 6.3 Funkcje publiczne

| Funkcja | Co zwraca |
|---------|-----------|
| `get_tier(dt_utc)` | Tier dla zadanej chwili (weekend → GREEN) |
| `next_tier_change(dt_utc)` | `(nowy_tier, moment_UTC)` najbliższej zmiany, lookahead 7 dni |
| `next_red_start(dt_utc)` | Moment startu najbliższego okna RED (jeśli teraz RED → *kolejnego*) |
| `red_window_end(dt_utc)` | Kiedy skończy się aktualne RED, lub `None` |
| `schedule_for_hour_range(weekend=False)` | Lista 24 tierów dla wykresów |
| `reload_schedule()` | Czyści cache, wymusza ponowne wczytanie TOML |

---

## 7. Pliki stanu (SQLite)

Lokalizacja: `~/.claude/`.

| Plik | Tworzony przez | Zawartość |
|------|----------------|-----------|
| `tost_ping.db` | `tost ping-collect` | Surowe pomiary latency (ping_raw) + flagi synced |
| `tost_taryfa.db` | `taryfa.scan_new_records()` | Kubełki godzinowe + offsety JSONL + mapowanie Notion + cache DB_ID |
| `tost_sonar.wav` | `sound.py` | Cache wygenerowanego proceduralnie WAV sonaru (~10 KB) |
| `tost_sonar_disabled` | klawisz `s` w THC | Plik-marker: obecność = sonar OFF |

Wszystkie SQLite w WAL mode (`PRAGMA journal_mode=WAL`) — bezpieczne dla równoległych procesów (THC czyta gdy `ping-collect` pisze).

---

## 8. Notion integration (opcjonalna)

THC **nie** pisze do Notion. To robi kolektor w tle:

| Env var | Baza | Częstotliwość | Co synchronizuje |
|---------|------|---------------|------------------|
| `PING_NOTION_DB_ID` | hourly ping | co 30 min (`tost ping-collect`) | Aggregaty godzinowe latency |
| `THC_NOTION_DB_ID` | THC 15-min | co 15 min (`tost ping-collect`) | 15-min buckety z polem Tier |
| `TARYFA_NOTION_DB_ID` lub `TARYFA_NOTION_PARENT_PAGE_ID` | Taryfa | co 15 min (`tost sync`) | Kubełki godzinowe z taryfą |

Brak env var → tylko lokalny zapis w SQLite, TUI działa normalnie.

---

## 9. Sonar — dźwiękowy sygnał po pingu

Moduł: `tost/sound.py`. Gra po każdym pomyślnym pingu (target=`api`), nie duplikuje dla pary api+status.

Charakter dźwięku:
- Log-sweep `800 Hz → 440 Hz` w ~220 ms (opadająca terca — klasyczny sonar)
- Exponential decay (τ ≈ 80 ms)
- 3 ms attack envelope (anty-klik)
- Peak ~−10 dBFS (delikatny)

Toggle: klawisz `s` w THC → tworzy/usuwa plik-marker `~/.claude/tost_sonar_disabled`. Widoczny w panelu TARYFA jako `sonar ●/○`. Domyślnie ON.

Platformy: Windows (`winsound` stdlib). Linux/macOS — no-op bez błędów.

---

## 10. Glossary — skróty i pojęcia

| Skrót | Rozwinięcie | Znaczenie |
|-------|-------------|-----------|
| **CET** | Central European Time | UTC+1 (zima) — główny zegar w THC |
| **CEST** | Central European Summer Time | UTC+2 (lato, DST) |
| **EST/EDT** | Eastern Standard/Daylight Time | USA wschodnie wybrzeże, UTC−5/−4 |
| **PST/PDT** | Pacific Standard/Daylight Time | USA zachodnie wybrzeże, UTC−8/−7 |
| **UTC** | Coordinated Universal Time | Baza czasowa — wszystkie obliczenia tierów + baseline są w UTC |
| **TTFB** | Time To First Byte | Od requestu do pierwszego bajtu odpowiedzi serwera — kluczowa metryka latency |
| **DNS** | Domain Name System | Czas lookup `api.anthropic.com` → IP |
| **TLS** | Transport Layer Security | Szyfrowany handshake (wliczony w `connect_ms` razem z TCP) |
| **MAD** | Median Absolute Deviation | Odporny estymator rozrzutu: `median(|x - median|)`. Mniej wrażliwy na outliery niż stdev |
| **p75 / p90** | Percentyle 75 / 90 | 75% / 90% wartości baselinu jest poniżej tego progu |
| **z-score** | Standard score | `(projected - median) / (1.4826 × MAD)` — liczba "MAD-stdev" od mediany |
| **ratio** | Burn ratio | `tokens_so_far / (median × elapsed_fraction)` — ile razy szybciej niż norma |
| **projected** | Projekcja | `tokens_so_far / elapsed_fraction` — ile tokenów zużyjesz do końca godziny przy aktualnym tempie |
| **baseline_used** | Źródło baselinu | `hour-of-day` (mediana z tej samej godziny w 7 dniach) / `all-day-fallback` (wszystkie godziny) / `insufficient` (brak danych) |
| **elapsed_fraction** | Ułamek upłynionej godziny | `(minute*60 + second) / 3600`, clamped ≥ 1/3600 |
| **Tier** | Strefa zagrożenia serwera | GREEN/YELLOW/ORANGE/RED wg harmonogramu godziny UTC |
| **Taryfa** | Strefa burn-rate tokenów | ZIELONA/ZOLTA/POMARANCZOWA/CZERWONA wg algorytmu taryfy |
| **◈** | Diamond marker | Wizualny prefiks nagłówków paneli |
| **●** | Filled circle | Kropka koloru tieru/taryfy |
| **███** | Block bar | Pełny blok — wizualna waga wskaźnika w NACISK NA LIMITY |
| **1fr / 2fr** | Fraction units (Textual CSS) | Proporcje elastycznej przestrzeni — 2fr bierze 2× więcej niż 1fr |

---

## 11. Gdzie co edytować — ściągawka

| Co chcesz zmienić | Plik | Uwagi |
|-------------------|------|-------|
| Godzina → tier (harmonogram) | `tost/thc_tiers.toml` | `Ctrl+R` reload |
| Progi ratio/z-score taryfy | `tost/taryfa_thresholds.toml` | `Ctrl+R` reload |
| Progi wskaźnika PING 1h | `tost/thc.py` → `_ping_pressure_level()` | Wymaga restartu (hardkod) |
| Progi wskaźnika BURN (labeluje reading.taryfa) | Przez `taryfa_thresholds.toml` | `Ctrl+R` reload |
| Wysokości paneli | `tost/thc.py` → `ThcApp.CSS` | Wymaga restartu |
| Odświeżanie | `tost/thc.py` → `REFRESH_INTERVAL = 5.0` | Wymaga restartu |
| Interval pomiaru pingu | `tost/ping.py` → `PingConfig.ping_interval` | Dotyczy `ping-collect`, nie THC |
| Char/decay sonaru | `tost/sound.py` → stałe na górze | Po zmianie usuń `~/.claude/tost_sonar.wav` żeby wygenerować od nowa |
| Strefy głównego zegara | `tost/thc.py` → stałe `CET_TZ/US_EAST_TZ/US_WEST_TZ` | Import `zoneinfo.ZoneInfo("Europe/…")` |

---

## 12. Gotcha

- **tzdata na Windows** — bez pakietu `tzdata` `ZoneInfo("Europe/Warsaw")` rzuci wyjątek → fallback na sztywne offsety (bez DST). Pakiet jest w `pyproject.toml` warunkowo dla `sys_platform == 'win32'`. Jeśli instalowałeś dev-mode przed tą zmianą: `pip install tzdata`.
- **Brak danych JSONL** — jeśli `~/.claude/projects/` jest puste (świeża instalka CC), taryfa pokaże `● BRAK — brak danych JSONL`. Dopiero po kilku sesjach pojawi się `● ZIELONA — zbieram dane`.
- **Pierwsze 7 dni** — baseline potrzebuje 5+ próbek per godzina UTC. Przed tym: `baseline_used = "all-day-fallback"` lub `"insufficient"`. Taryfa nie jest miarodajna w tym okresie.
- **Brak ping-collect** — panel `PING` i wskaźnik `PING 1h` będą puste. Uruchom osobnym procesem: `tost ping-collect`.
- **Weekend** — tier zawsze GREEN niezależnie od `thc_tiers.toml`. Jeśli Anthropic obciąży serwery w weekend (np. promocje), nie odzwierciedla się to w tierze — ale BURN i PING pokażą prawdę.
- **`ping-collect` vs THC** — THC to read-only viewer. Bez `ping-collect` w tle nie ma świeżych danych pingu.
- **SQLite locking** — WAL mode eliminuje konflikty przy współbieżnych procesach, ale nie ustaw obu TUI na tę samą bazę z włączonym `journal_mode=DELETE`.

---

## 13. Referencje

- Kod TUI: `tost/thc.py`
- Tier engine: `tost/thc_tiers.py` + `thc_tiers.toml`
- Taryfa engine: `tost/taryfa.py` + `taryfa_thresholds.toml`
- Ping engine: `tost/ping.py` (daemon + SQLite)
- Sonar: `tost/sound.py`
- Notion sync taryfy: `tost/taryfa_notion.py`
- Scanner JSONL: `tost/jsonl_scanner.py`
- Cennik modeli: `tost/cost.py`
- CLI entry: `tost/cli.py` → `tost thc`
- Skrót Windows: `create-shortcut-thc.ps1`
