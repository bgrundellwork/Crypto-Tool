"""Interval mapping utilities used across ingestion, APIs, and backtests."""

from __future__ import annotations

from typing import Dict


INTERVAL_SECONDS: Dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14_400,
    "1d": 86_400,
    "1w": 604_800,
}


def get_interval_seconds(interval: str) -> int:
    """
    Returns the interval duration in seconds or raises ValueError if unknown.
    """
    try:
        return INTERVAL_SECONDS[interval]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unsupported interval '{interval}'") from exc
