# app/services/ingestion/gap_detector.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Candle
from app.jobs.scheduler import timeframe_seconds


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _floor_to_step(dt: datetime, step_seconds: int) -> datetime:
    dt = _utc(dt)
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % step_seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


@dataclass(frozen=True)
class Gap:
    start: datetime  # inclusive
    end: datetime    # exclusive


async def get_existing_candle_times(
    session: AsyncSession,
    coin: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> List[datetime]:
    start = _utc(start)
    end = _utc(end)

    q = (
        select(Candle.ts)
        .where(
            Candle.coin == coin,
            Candle.interval == interval,
            Candle.ts >= start,
            Candle.ts < end,
        )
        .order_by(Candle.ts.asc())
    )
    res = await session.execute(q)
    return [row[0].replace(tzinfo=timezone.utc) if row[0].tzinfo is None else row[0].astimezone(timezone.utc) for row in res.all()]


def detect_gaps(
    existing_times: List[datetime],
    interval: str,
    start: datetime,
    end: datetime,
) -> List[Gap]:
    step = timeframe_seconds(interval)
    start = _floor_to_step(start, step)
    end = _utc(end)

    existing = sorted({_floor_to_step(t, step) for t in existing_times})
    existing_set = set(existing)

    gaps: List[Gap] = []
    cur = start

    while cur < end:
        if cur in existing_set:
            cur = cur + timedelta(seconds=step)
            continue

        gap_start = cur
        # advance until we hit an existing candle or end
        while cur < end and cur not in existing_set:
            cur = cur + timedelta(seconds=step)
        gap_end = cur
        gaps.append(Gap(gap_start, gap_end))

    return gaps
