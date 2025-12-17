# app/services/candle_reader.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, asc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Candle


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_dict(c: Candle) -> dict[str, Any]:
    ts = c.ts
    if isinstance(ts, datetime):
        ts = _to_utc(ts)
    return {
        "timestamp": ts,
        "open": float(c.open),
        "high": float(c.high),
        "low": float(c.low),
        "close": float(c.close),
        # volume may be NULL (that’s okay)
        "volume": float(c.volume) if c.volume is not None else None,
    }


async def fetch_candles_from_db(
    session: AsyncSession,
    *,
    coin: str,
    interval: str,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Read candles from the candles table (your ingestion output).
    Returns list of dicts with keys: timestamp, open, high, low, close, volume.
    """
    q = select(Candle).where(Candle.coin == coin, Candle.interval == interval).order_by(asc(Candle.ts))

    if start_ts is not None:
        q = q.where(Candle.ts >= _to_utc(start_ts))

    if end_ts is not None:
        q = q.where(Candle.ts < _to_utc(end_ts))

    if limit is not None:
        q = q.limit(int(limit))

    res = await session.execute(q)
    rows = res.scalars().all()
    return [_row_to_dict(r) for r in rows]

