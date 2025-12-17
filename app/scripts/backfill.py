# app/scripts/backfill.py
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone, timedelta

from app.db.session import session_factory, engine
from app.services.ingestion.gap_detector import get_existing_candle_times, detect_gaps
from app.services.ingestion.candles_ingestion import ingest_range


def _utc_dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


async def run(coin: str, interval: str, start: datetime, end: datetime) -> None:
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)

    async with session_factory() as session:
        existing = await get_existing_candle_times(session, coin, interval, start, end)
        gaps = detect_gaps(existing, interval, start, end)

    if not gaps:
        print("✅ no gaps detected")
        return

    print(f"🧩 gaps detected: {len(gaps)}")
    total_inserted = 0

    for g in gaps:
        print(f"⛏️ filling gap: {g.start.isoformat()} -> {g.end.isoformat()}")
        async with session_factory() as session:
            inserted = await ingest_range(
                session=session,
                coin=coin,
                interval=interval,
                start_ts=g.start,
                end_ts=g.end,
            )
        total_inserted += inserted
        print(f"✅ inserted={inserted}")

    print(f"🏁 backfill complete | total_inserted={total_inserted}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coin", required=True)
    p.add_argument("--interval", required=True)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--start", default=None)  # YYYY-MM-DD
    p.add_argument("--end", default=None)    # YYYY-MM-DD
    args = p.parse_args()

    now = datetime.now(timezone.utc)

    if args.days is not None:
        start = now - timedelta(days=args.days)
        end = now
    else:
        if not args.start or not args.end:
            raise SystemExit("Use either --days N OR --start YYYY-MM-DD --end YYYY-MM-DD")
        start = _utc_dt(args.start)
        end = _utc_dt(args.end)

    try:
        asyncio.run(run(args.coin, args.interval, start, end))
    finally:
        try:
            asyncio.run(engine.dispose())
        except Exception:
            pass


if __name__ == "__main__":
    main()

