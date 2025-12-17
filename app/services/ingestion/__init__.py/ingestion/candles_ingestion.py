# app/services/ingestion/candles_ingestion.py
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle
from app.services.candles import get_candles  # <-- your existing function


async def _latest_ts(session: AsyncSession, source: str, coin: str, interval: str) -> datetime | None:
    q = (
        select(Candle.ts)
        .where(Candle.source == source, Candle.coin == coin, Candle.interval == interval)
        .order_by(Candle.ts.desc())
        .limit(1)
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()


def _to_utc(dt: datetime) -> datetime:
    # your get_candles uses datetime.utcfromtimestamp(bucket) -> naive UTC
    # make it timezone-aware so DB is consistent
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


async def upsert_candles(session: AsyncSession, rows: list[dict]) -> int:
    if not rows:
        return 0

    # SQLite-friendly UPSERT
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    values = []
    for r in rows:
        values.append({
            "source": "local",                 # since you’re deriving from MarketSnapshot DB
            "coin": r["coin"],
            "interval": r["interval"],
            "ts": _to_utc(r["timestamp"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0.0) or 0.0),
        })

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
    source = "local"

    latest = await _latest_ts(session, source, coin, interval)

    # Pull candles starting from latest candle time (safe; upsert prevents duplicates)
    candles = await get_candles(coin=coin, interval=interval, start_ts=latest)

    # attach metadata the upsert expects
    for c in candles:
        c["coin"] = coin
        c["interval"] = interval

    n = await upsert_candles(session, candles)
    await session.commit()
    return n
