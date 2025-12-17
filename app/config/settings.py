# app/config/settings.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


def parse_csv(value: str | None, default: List[str]) -> List[str]:
    if not value:
        return default
    items = [x.strip() for x in value.split(",")]
    return [x for x in items if x]


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def parse_schedule_seconds(value: str | None) -> Optional[Dict[str, int]]:
    """
    Supports:
      - JSON: {"1m":30,"5m":120}
      - CSV map: "1m=30,5m=120,15m=300"
    """
    if not value:
        return None

    v = value.strip()
    if v.startswith("{"):
        data = json.loads(v)
        return {str(k): int(v) for k, v in data.items()}

    out: Dict[str, int] = {}
    for part in v.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Bad INGEST_SCHEDULE_SECONDS part: {part}")
        k, val = part.split("=", 1)
        out[k.strip()] = int(val.strip())
    return out


@dataclass(frozen=True)
class Settings:
    MARKET_DB_URL: str
    INGEST_ENABLED: bool
    INGEST_COINS: List[str]
    INGEST_INTERVALS: List[str]
    INGEST_SCHEDULE_SECONDS: Optional[Dict[str, int]]
    INGEST_LOOKBACK_DAYS: int
    SCHEDULER_LOCK_PATH: str

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            MARKET_DB_URL=os.getenv("MARKET_DB_URL", "sqlite+aiosqlite:///./market.db"),
            INGEST_ENABLED=parse_bool(os.getenv("INGEST_ENABLED"), True),
            INGEST_COINS=parse_csv(os.getenv("INGEST_COINS"), ["bitcoin"]),
            INGEST_INTERVALS=parse_csv(os.getenv("INGEST_INTERVALS"), ["15m"]),
            INGEST_SCHEDULE_SECONDS=parse_schedule_seconds(os.getenv("INGEST_SCHEDULE_SECONDS")),
            INGEST_LOOKBACK_DAYS=parse_int(os.getenv("INGEST_LOOKBACK_DAYS"), 3),
            SCHEDULER_LOCK_PATH=os.getenv("SCHEDULER_LOCK_PATH", "./scheduler.lock"),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
