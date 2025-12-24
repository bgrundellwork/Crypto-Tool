from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_DUPLICATE_CANDLES_SQL = """
    SELECT coin, interval, ts, COUNT(*) AS count
    FROM candles
    GROUP BY coin, interval, ts
    HAVING count > 1
"""

_NON_MONOTONIC_SQL = """
    WITH ordered AS (
        SELECT
            coin,
            interval,
            ts,
            LAG(ts) OVER (PARTITION BY coin, interval ORDER BY ts) AS prev_ts
        FROM candles
    )
    SELECT coin, interval, ts, prev_ts
    FROM ordered
    WHERE prev_ts IS NOT NULL AND ts < prev_ts
"""


async def verify_candle_invariants(session: AsyncSession, *, strict: bool = True) -> dict[str, list[dict]]:
    """
    When strict=True: raise AssertionError if any findings exist.
    strict=False: return findings without raising.
    """
    findings: dict[str, list[dict]] = {"duplicates": [], "non_monotonic": []}

    dup = await session.execute(text(_DUPLICATE_CANDLES_SQL))
    for row in dup.mappings():
        findings["duplicates"].append(
            {
                "coin": row["coin"],
                "interval": row["interval"],
                "ts": row["ts"],
                "count": row["count"],
            }
        )

    non_mono = await session.execute(text(_NON_MONOTONIC_SQL))
    for row in non_mono.mappings():
        findings["non_monotonic"].append(
            {
                "coin": row["coin"],
                "interval": row["interval"],
                "ts": row["ts"],
                "prev_ts": row["prev_ts"],
            }
        )

    if strict and (findings["duplicates"] or findings["non_monotonic"]):
        raise AssertionError(f"Candle invariants violated: {findings}")

    return findings
