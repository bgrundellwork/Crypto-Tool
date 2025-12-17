# app/config/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional


def parse_csv(s: str | None) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def parse_bool(s: str | None, default: bool) -> bool:
    if s is None:
        return default
    return s.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_int(s: str | None, default: int) -> int:
    try:
        return int(s) if s is not None else default
    except Exception:
        return default


def parse_float(s: str | None, default: float) -> float:
    try:
        return float(s) if s is not None else default
    except Exception:
        return default


def parse_schedule_map(s: str | None) -> Optional[Dict[str, int]]:
    """
    Optional env format:
      INGEST_SCHEDULE_SECONDS="5m=30,15m=60,1h=300"
    """
    if not s:
        return None

    out: Dict[str, int] = {}
    parts = [p.strip() for p in s.split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue
        try:
            out[k] = int(v)
        except Exception:
            continue

    return out or None


@dataclass(frozen=True)
class Settings:
    # -------------------------
    # DB
    # -------------------------
    MARKET_DB_URL: str = field(default_factory=lambda: os.getenv("MARKET_DB_URL", "sqlite+aiosqlite:///./market.db"))

    # -------------------------
    # Candle ingestion
    # -------------------------
    INGEST_ENABLED: bool = field(default_factory=lambda: parse_bool(os.getenv("INGEST_ENABLED"), True))

    # IMPORTANT: use default_factory so this is not treated as a mutable default
    INGEST_COINS: List[str] = field(
        default_factory=lambda: parse_csv(os.getenv("INGEST_COINS", "bitcoin,ethereum,solana"))
    )

    INGEST_INTERVALS: List[str] = field(
        default_factory=lambda: parse_csv(os.getenv("INGEST_INTERVALS", "5m,15m,1h"))
    )

    # Optional mapping, may be None
    INGEST_SCHEDULE_SECONDS: Optional[Dict[str, int]] = field(
        default_factory=lambda: parse_schedule_map(os.getenv("INGEST_SCHEDULE_SECONDS"))
    )

    INGEST_LOOKBACK_DAYS: int = field(default_factory=lambda: parse_int(os.getenv("INGEST_LOOKBACK_DAYS"), 3))

    SCHEDULER_LOCK_PATH: str = field(default_factory=lambda: os.getenv("SCHEDULER_LOCK_PATH", "./scheduler.lock"))

    # -------------------------
    # Snapshot collection
    # -------------------------
    SNAPSHOT_ENABLED: bool = field(default_factory=lambda: parse_bool(os.getenv("SNAPSHOT_ENABLED"), True))
    SNAPSHOT_INTERVAL_SECONDS: int = field(default_factory=lambda: parse_int(os.getenv("SNAPSHOT_INTERVAL_SECONDS"), 60))
    SNAPSHOT_MAX_RETRIES: int = field(default_factory=lambda: parse_int(os.getenv("SNAPSHOT_MAX_RETRIES"), 5))
    SNAPSHOT_BACKOFF_BASE_SECONDS: int = field(
        default_factory=lambda: parse_int(os.getenv("SNAPSHOT_BACKOFF_BASE_SECONDS"), 1)
    )
    SNAPSHOT_JITTER_SECONDS: float = field(default_factory=lambda: parse_float(os.getenv("SNAPSHOT_JITTER_SECONDS"), 0.5))
    SNAPSHOT_STALE_THRESHOLD_MINUTES: int = field(
        default_factory=lambda: parse_int(os.getenv("SNAPSHOT_STALE_THRESHOLD_MINUTES"), 10)
    )
    SNAPSHOT_LOCK_PATH: str = field(default_factory=lambda: os.getenv("SNAPSHOT_LOCK_PATH", "./snapshot.lock"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
