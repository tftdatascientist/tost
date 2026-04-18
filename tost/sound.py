"""Sonar ping — krótki, delikatny dźwięk jak z okrętu podwodnego.

Generuje WAV proceduralnie (bez zewnętrznych assetów) i cache'uje go w
`~/.claude/tost_sonar.wav`. Odtwarzanie nieblokujące przez `winsound.PlaySound(SND_ASYNC)`.

Charakter dźwięku:
    - Log-sweep 800 Hz → 440 Hz w ~220 ms (opadająca terca — klasyczny sonar)
    - Exponential decay (τ ≈ 80 ms) — szybkie wygaszenie jak echo
    - 3 ms attack envelope — bez kliknięcia na starcie
    - Peak ~-10 dBFS — delikatny, nie zaskakuje

Włącznik: plik-marker `~/.claude/tost_sonar_disabled`. Obecność = OFF,
brak = ON (domyślnie ON bez konieczności zapisu przy pierwszym uruchomieniu).
THC TUI toggluje ten plik przez klawisz `s`.

Platformy: Windows (winsound stdlib). Na innych — no-op bez błędów.
"""

from __future__ import annotations

import logging
import math
import struct
import sys
import wave
from pathlib import Path

log = logging.getLogger("tost.sound")

SONAR_WAV_PATH = Path.home() / ".claude" / "tost_sonar.wav"
SONAR_DISABLED_MARKER = Path.home() / ".claude" / "tost_sonar_disabled"

# Parametry generatora (dobrane ręcznie żeby brzmiał "sonarowo")
SAMPLE_RATE    = 22050
DURATION_SEC   = 0.38     # dłuższy ogon — lepiej słyszalny
START_FREQ     = 800.0
END_FREQ       = 440.0
PEAK_AMPLITUDE = 0.72     # ~-2.8 dBFS (decay szybko opada, więc brak clippingu)
DECAY_TAU      = 0.14     # wolniejsze wygaszenie — „dzwoni" jak sonar
ATTACK_SEC     = 0.003    # anty-klik

# Wersja parametrów — zmiana wymusi regenerację cache'owanego WAV-a.
SONAR_PARAMS_VERSION = 2


def _version_file(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".ver")


def _wav_is_current(path: Path = SONAR_WAV_PATH) -> bool:
    """True gdy cached WAV zgadza sie z aktualna wersja parametrow."""
    if not path.exists():
        return False
    try:
        return int(_version_file(path).read_text().strip()) == SONAR_PARAMS_VERSION
    except (OSError, ValueError):
        return False


def generate_sonar_wav(path: Path = SONAR_WAV_PATH) -> Path:
    """Wygeneruj plik WAV (16-bit mono PCM) z dźwiękiem sonaru."""
    n_samples = int(SAMPLE_RATE * DURATION_SEC)
    frames = bytearray()
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        # log-sweep START → END
        freq = START_FREQ * (END_FREQ / START_FREQ) ** (t / DURATION_SEC)
        # exponential decay
        decay = math.exp(-t / DECAY_TAU)
        # attack ramp
        attack = min(1.0, t / ATTACK_SEC) if ATTACK_SEC > 0 else 1.0
        sample = PEAK_AMPLITUDE * attack * decay * math.sin(2.0 * math.pi * freq * t)
        pcm = int(max(-1.0, min(1.0, sample)) * 32767)
        frames.extend(struct.pack("<h", pcm))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(frames))
    try:
        _version_file(path).write_text(str(SONAR_PARAMS_VERSION))
    except OSError as e:
        log.debug("Nie mozna zapisac wersji sonaru: %s", e)
    return path


def is_enabled() -> bool:
    """True gdy sonar może grać (brak pliku-markera disabled)."""
    return not SONAR_DISABLED_MARKER.exists()


def set_enabled(enabled: bool) -> bool:
    """Włącz/wyłącz sonar. Zwraca nowy stan (True=ON)."""
    SONAR_DISABLED_MARKER.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        if SONAR_DISABLED_MARKER.exists():
            try:
                SONAR_DISABLED_MARKER.unlink()
            except OSError as e:
                log.warning("Nie mozna usunac sonar-disabled marker: %s", e)
    else:
        try:
            SONAR_DISABLED_MARKER.touch()
        except OSError as e:
            log.warning("Nie mozna utworzyc sonar-disabled marker: %s", e)
    return is_enabled()


def toggle_enabled() -> bool:
    """Przełącz stan (ON↔OFF). Zwraca nowy stan."""
    return set_enabled(not is_enabled())


def play_sonar() -> None:
    """Odtwórz sonar nieblokująco. No-op jeśli wyłączony lub nie-Windows."""
    if not is_enabled():
        return
    if sys.platform != "win32":
        # Future: można dodać `afplay` (macOS) lub `aplay` (Linux) subprocess
        return
    try:
        import winsound  # type: ignore[import-not-found]
        if not _wav_is_current():
            generate_sonar_wav()
        winsound.PlaySound(
            str(SONAR_WAV_PATH),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except Exception as e:  # noqa: BLE001 — graceful fallback
        log.debug("Sonar play failed: %s", e)
