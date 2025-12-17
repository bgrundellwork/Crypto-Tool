# app/db/bootstrap.py
from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine


async def ensure_db_primitives() -> None:
    """
    SQLite-friendly bootstrapping:
    - Create indexes if missing
    - Create UNIQUE index for candles(symbol, interval, open_time)
      (acts as both integrity + performance)
    """
    stmts = [
        # Uniqueness for candles (also an index)
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_candles_symbol_interval_open_time
        ON candles(symbol, interval, open_time);
        """,
        # Snapshot range reads
        """
        CREATE INDEX IF NOT EXISTS ix_market_snapshots_symbol_timestamp
        ON market_snapshots(symbol, timestamp);
        """,
        # Optional extra index (only if you frequently filter without open_time)
        """
        CREATE INDEX IF NOT EXISTS ix_candles_symbol_interval
        ON candles(symbol, interval);
        """,
    ]

    async with engine.begin() as conn:
        for s in stmts:
            await conn.execute(text(s))
