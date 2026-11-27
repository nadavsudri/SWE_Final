"""API settings. Thresholds are constants here (overridable by env), never in UI code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WARN_KM2 = 20_000     # warn: big areas make the Overpass queries slow and can time out
MAX_KM2 = 100_000     # block: too large to fetch reliably


@dataclass(frozen=True)
class Settings:
    root: Path = Path("data/raw")
    processed: Path | None = None  # default: <root>/../processed
    warn_km2: float = WARN_KM2
    max_km2: float = MAX_KM2
    env_file: Path = Path(".env")

    @classmethod
    def from_env(cls) -> "Settings":
        p = os.environ.get("LEG_PROCESSED_ROOT")
        return cls(root=Path(os.environ.get("LEG_CACHE_ROOT", "data/raw")), processed=Path(p) if p else None,
                   warn_km2=float(os.environ.get("LEG_WARN_KM2", WARN_KM2)),
                   max_km2=float(os.environ.get("LEG_MAX_KM2", MAX_KM2)))

    @property
    def processed_root(self) -> Path:
        return self.processed or self.root.parent / "processed"

    @property
    def advice_root(self) -> Path:
        return self.root.parent / "advice"
