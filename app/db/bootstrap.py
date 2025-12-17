# app/db/bootstrap.py
from __future__ import annotations

from sqlalchemy import text
from app.db.session import engine


async def ensure_db_primitives() -> None:
    stmts = [
        # Candles: uniqueness + fast range reads
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_candles_source_coin_interval_ts
        ON candles(source, coin, interval, ts);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_candles_coin_interval_ts
        ON candles(coin, interval, ts);
        """,
        # Snapshots: fast reads by coin/time
        """
        CREATE INDEX IF NOT EXISTS ix_market_snapshots_coin_id_timestamp
        ON market_snapshots(coin_id, timestamp);
        """,
    ]

    async with engine.begin() as conn:
        for s in stmts:
            try:
                await conn.execute(text(s))
            except Exception as e:
                print(f"⚠️ DB bootstrap skipped a statement due to schema mismatch: {e}")
