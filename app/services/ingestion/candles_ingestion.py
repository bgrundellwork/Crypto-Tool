# app/services/ingestion/candles_ingestion.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Candle
from app.services.candles import get_candles


def _to_utc(dt: datetime) -> datetime:
    # your get_candles uses datetime.utcfromtimestamp(bucket) => naive UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _latest_ts(session: AsyncSession, source: str, coin: str, interval: str) -> datetime | None:
    q = (
        select(Candle.ts)
        .where(Candle.source == source, Candle.coin == coin, Candle.interval == interval)
        .order_by(Candle.ts.desc())
        .limit(1)
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()


async def upsert_candles(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    values: list[dict[str, Any]] = []
    for r in rows:
        values.append(
            {
                "source": r.get("source", "local"),
                "coin": r["coin"],
                "interval": r["interval"],
                "ts": _to_utc(r["timestamp"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0.0) or 0.0),
            }
        )

    stmt = sqlite_insert(Candle).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "coin", "interval", "ts"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)
    return len(values)


async def ingest_latest(session: AsyncSession, coin: str, interval: str) -> int:
    """
    Build candles from your MarketSnapshot table (via get_candles)
    and store them into the candles table.
    """
    source = "local"

    latest = await _latest_ts(session, source, coin, interval)

    # Pull candles starting from latest candle time (safe: upsert prevents duplicates)
    candles = await get_candles(coin=coin, interval=interval, start_ts=latest)

    # attach metadata required for the Candle table
    for c in candles:
        c["coin"] = coin
        c["interval"] = interval
        c["source"] = source

    n = await upsert_candles(session, candles)
    await session.commit()
    return n


async def ingest_range(
    session: AsyncSession,
    coin: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
) -> int:
    """
    Ingest a bounded time window [start_ts, end_ts) built from snapshots.

    NOTE: get_candles() currently supports start_ts; we filter end_ts here.
    """
    source = "local"

    start_ts = _to_utc(start_ts)
    end_ts = _to_utc(end_ts)

    candles = await get_candles(coin=coin, interval=interval, start_ts=start_ts)

    # Filter to [start_ts, end_ts)
    candles = [c for c in candles if start_ts <= _to_utc(c["timestamp"]) < end_ts]

    for c in candles:
        c["coin"] = coin
        c["interval"] = interval
        c["source"] = source

    n = await upsert_candles(session, candles)
    await session.commit()
    return n
