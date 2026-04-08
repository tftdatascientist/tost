"""Configuration loading from TOML with sensible defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CollectorConfig:
    host: str = "0.0.0.0"
    port: int = 4318


@dataclass
class DatabaseConfig:
    path: str = "tost.db"


@dataclass
class BaselineConfig:
    input_tokens_per_message: int = 3000
    output_tokens_per_message: int = 100


@dataclass
class DisplayConfig:
    refresh_interval: float = 2.0


@dataclass
class TostConfig:
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)


def load_config(path: str | Path | None = None) -> TostConfig:
    """Load config from TOML file. Falls back to defaults if file not found."""
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        candidates.append(Path("tost.toml"))
        candidates.append(Path.home() / ".config" / "tost" / "tost.toml")

    raw: dict = {}
    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, "rb") as f:
                raw = tomllib.load(f)
            break

    cfg = TostConfig()

    if "collector" in raw:
        cfg.collector = CollectorConfig(**{
            k: v for k, v in raw["collector"].items()
            if k in CollectorConfig.__dataclass_fields__
        })
    if "database" in raw:
        cfg.database = DatabaseConfig(**{
            k: v for k, v in raw["database"].items()
            if k in DatabaseConfig.__dataclass_fields__
        })
    if "baseline" in raw:
        cfg.baseline = BaselineConfig(**{
            k: v for k, v in raw["baseline"].items()
            if k in BaselineConfig.__dataclass_fields__
        })
    if "display" in raw:
        cfg.display = DisplayConfig(**{
            k: v for k, v in raw["display"].items()
            if k in DisplayConfig.__dataclass_fields__
        })

    return cfg
