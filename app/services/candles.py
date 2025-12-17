from datetime import datetime
from collections import defaultdict
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import MarketSnapshot


INTERVALS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400,
}


async def get_candles(
    coin: str,
    interval: str,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
):
    seconds = INTERVALS.get(interval)
    if not seconds:
        raise ValueError("Invalid interval")

    async with SessionLocal() as session:
        query = (
            select(MarketSnapshot)
            .where(MarketSnapshot.coin_id == coin)
        )

        if start_ts:
            query = query.where(MarketSnapshot.timestamp >= start_ts)
        if end_ts:
            query = query.where(MarketSnapshot.timestamp <= end_ts)

        query = query.order_by(MarketSnapshot.timestamp.asc())

        result = await session.execute(query)
        rows = result.scalars().all()

    buckets = defaultdict(list)

    for row in rows:
        bucket = int(row.timestamp.timestamp()) // seconds * seconds
        buckets[bucket].append(row)

    candles = []
    for bucket in sorted(buckets):
        snaps = buckets[bucket]
        prices = [s.price for s in snaps]

        candles.append({
            "timestamp": datetime.utcfromtimestamp(bucket),
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(s.volume for s in snaps),
        })

    return candles
