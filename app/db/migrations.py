from __future__ import annotations

from typing import Sequence

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import engine as default_engine

_CANDLE_DUP_SQL = """
    SELECT coin, interval, ts, COUNT(*) AS count
    FROM candles
    GROUP BY coin, interval, ts
    HAVING count > 1
    LIMIT 1
"""

_SNAPSHOT_DUP_SQL = """
    SELECT coin_id, timestamp, COUNT(*) AS count
    FROM market_snapshots
    GROUP BY coin_id, timestamp
    HAVING count > 1
    LIMIT 1
"""

_STATEMENTS: Sequence[str] = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_candles_coin_interval_ts
    ON candles(coin, interval, ts);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_candles_coin_interval_ts_desc
    ON candles(coin, interval, ts DESC);
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_market_snapshots_coin_ts
    ON market_snapshots(coin_id, timestamp);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_market_snapshots_coin_ts
    ON market_snapshots(coin_id, timestamp);
    """,
)


async def enforce_integrity_constraints(engine: AsyncEngine | None = None) -> None:
    """
    Ensures uniqueness + ordering indexes exist and fails fast if duplicates are present.
    """
    eng = engine or default_engine

    async with eng.begin() as conn:
        await _assert_no_duplicates(conn, _CANDLE_DUP_SQL, "candles", ("coin", "interval", "ts"))
        await _assert_no_duplicates(conn, _SNAPSHOT_DUP_SQL, "market_snapshots", ("coin_id", "timestamp"))

        for stmt in _STATEMENTS:
            try:
                await conn.execute(text(stmt))
            except ProgrammingError as exc:
                raise RuntimeError(f"Failed to apply integrity DDL: {stmt}") from exc


async def _assert_no_duplicates(conn, sql: str, table: str, keys: Sequence[str]) -> None:
    try:
        result = await conn.execute(text(sql))
    except Exception:
        # Table may not exist yet (fresh DB); skip validation.
        return

    row = result.first()
    if row:
        mapping = row._mapping
        joined_keys = ", ".join(f"{k}={mapping.get(k)}" for k in keys if k in mapping)
        raise RuntimeError(
            f"Duplicate rows detected in {table} for ({joined_keys}). Clean data before enforcing constraints."
        )
