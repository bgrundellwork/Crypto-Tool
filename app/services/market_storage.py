from datetime import timedelta
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import MarketSnapshot
from app.utils.time import utcnow


WRITE_WINDOW_SECONDS = 60  # dedupe window


async def store_market_snapshots(market_data: list[dict]) -> None:
    async with SessionLocal() as session:
        now = utcnow()
        cutoff = now - timedelta(seconds=WRITE_WINDOW_SECONDS)

        for coin in market_data:
            # 1️⃣ Check last snapshot for this coin
            result = await session.execute(
                select(MarketSnapshot)
                .where(MarketSnapshot.coin_id == coin["id"])
                .order_by(MarketSnapshot.timestamp.desc())
                .limit(1)
            )

            last_snapshot = result.scalar_one_or_none()

            # 2️⃣ Skip if recent snapshot exists
            if last_snapshot and last_snapshot.timestamp > cutoff:
                continue

            # 3️⃣ Write new snapshot
            snapshot = MarketSnapshot(
                coin_id=coin["id"],
                price=coin["current_price"],
                market_cap=coin["market_cap"],
                volume=coin["total_volume"],
                timestamp=now,
            )

            session.add(snapshot)

        await session.commit()
