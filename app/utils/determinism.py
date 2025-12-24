from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def canonical_json(payload: Any) -> str:
    """
    Serialize payload using deterministic ordering and formatting.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_str(data: str) -> str:
    return sha256_bytes(data.encode("utf-8"))


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hash_candles(candles: Iterable[Mapping[str, Any]]) -> str:
    normalized = []
    for candle in candles:
        ts = candle.get("timestamp") or candle.get("ts")
        if ts is None:
            raise ValueError("Candle missing timestamp field for hashing")
        normalized.append(
            {
                "ts": ensure_utc(ts).isoformat(),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
            }
        )
    return sha256_str(canonical_json(normalized))
