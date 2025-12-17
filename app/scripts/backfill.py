# scripts/backfill.py
from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timezone, timedelta

from app.db.session import session_factory

# ✅ IMPORTANT:
# Change this import + function name to match YOUR ingestion function.
# From your earlier plan, your file is likely: app/services/ingestion/candles_ingestion.py
# and the function might be ingest_candles(...) or similar.
from app.services.ingestion.candles_ingestion import ingest_candles  # <-- CHANGE IF NEEDED


def parse_date_yyyy_mm_dd(s: str) -> int:
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


async def run(symbol: str, interval: str, start_epoch: int, end_epoch: int) -> None:
    print(f"⛏️ backfill starting | {symbol} {interval} | {start_epoch} -> {end_epoch}")

    t0 = time.time()
    async with session_factory() as session:
        # If your ingest_candles supports start/end, keep these args.
        # If it DOES NOT, remove start/end and it will just do its default ingestion.
        inserted = await ingest_candles(
            session=session,
            symbol=symbol,
            interval=interval,
            start=start_epoch,
            end=end_epoch,
        )
        await session.commit()

    dt_ms = int((time.time() - t0) * 1000)
    print(f"✅ backfill done | inserted={inserted} | {dt_ms}ms")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True, help="coingecko id e.g. bitcoin, ethereum")
    p.add_argument("--interval", required=True, help="e.g. 1m, 5m, 15m, 1h")
    p.add_argument("--days", type=int, default=None, help="backfill last N days")
    p.add_argument("--start", default=None, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (UTC)")
    args = p.parse_args()

    now = datetime.now(timezone.utc)

    if args.days is not None:
        start_epoch = int((now - timedelta(days=args.days)).timestamp())
        end_epoch = int(now.timestamp())
    else:
        if not args.start or not args.end:
            raise SystemExit("Provide either --days N OR --start YYYY-MM-DD --end YYYY-MM-DD")
        start_epoch = parse_date_yyyy_mm_dd(args.start)
        end_epoch = parse_date_yyyy_mm_dd(args.end)

    asyncio.run(run(args.symbol, args.interval, start_epoch, end_epoch))


if __name__ == "__main__":
    main()
