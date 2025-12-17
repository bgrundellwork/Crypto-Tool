# app/services/ingestion/gap_detector.py
from __future__ import annotations

from datetime import datetime
from typing import List, Tuple, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.scheduler import timeframe_seconds


def _to_epoch_seconds(x: Any) -> int:
    if x is None:
        raise ValueError("open_time is None")
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return int(x)
    if isinstance(x, datetime):
        return int(x.timestamp())
    # string?
    try:
        # ISO string -> datetime
        dt = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        # last resort
        return int(x)


async def get_existing_open_times(
    session: AsyncSession,
    symbol: str,
    interval: str,
    start_epoch: int,
    end_epoch: int,
) -> List[int]:
    q = text("""
        SELECT open_time
        FROM candles
        WHERE symbol = :symbol
          AND interval = :interval
          AND open_time >= :start
          AND open_time < :end
        ORDER BY open_time ASC
    """)
    res = await session.execute(q, {"symbol": symbol, "interval": interval, "start": start_epoch, "end": end_epoch})
    rows = res.fetchall()
    return [_to_epoch_seconds(r[0]) for r in rows]


def detect_gaps(open_times: List[int], step_seconds: int, start_epoch: int, end_epoch: int) -> List[Tuple[int, int]]:
    """
    Returns gaps as (gap_start, gap_end) in epoch seconds.
    Missing slots of size step_seconds inside [start, end).
    """
    gaps: List[Tuple[int, int]] = []

    if start_epoch >= end_epoch:
        return gaps

    if not open_times:
        return [(start_epoch, end_epoch)]

    expected = start_epoch
    i = 0
    n = len(open_times)

    # Normalize: ensure sorted
    open_times = sorted(set(open_times))

    while expected < end_epoch:
        if i < n and open_times[i] == expected:
            expected += step_seconds
            i += 1
            continue

        # missing expected; find next existing time or end
        next_existing = open_times[i] if i < n else end_epoch
        gap_start = expected
        gap_end = min(next_existing, end_epoch)
        gaps.append((gap_start, gap_end))

        expected = gap_end
        # if expected equals an existing, loop will pick it up

    # Merge adjacent gaps
    merged: List[Tuple[int, int]] = []
    for gs, ge in gaps:
        if not merged:
            merged.append((gs, ge))
        else:
            ps, pe = merged[-1]
            if gs <= pe:
                merged[-1] = (ps, max(pe, ge))
            else:
                merged.append((gs, ge))

    return merged


def step_for_interval(interval: str) -> int:
    return timeframe_seconds(interval)
