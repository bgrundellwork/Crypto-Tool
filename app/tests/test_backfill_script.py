from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Candle
from app.scripts import backfill


BASE_TS = datetime(2024, 2, 1, tzinfo=timezone.utc)
STEP = timedelta(minutes=5)


@pytest_asyncio.fixture
async def sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield Session
    finally:
        await engine.dispose()


async def _seed(sessionmaker, timestamps):
    async with sessionmaker() as session:
        session.add_all(
            [
                Candle(
                    coin="btc",
                    interval="5m",
                    ts=ts,
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=1,
                )
                for ts in timestamps
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_execute_backfill_completes(monkeypatch, sessionmaker):
    timestamps = [BASE_TS, BASE_TS + 2 * STEP]
    await _seed(sessionmaker, timestamps)

    async def fake_ingest(session, coin, interval, start_ts, end_ts):
        session.add(
            Candle(
                coin=coin,
                interval=interval,
                ts=start_ts,
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        )
        await session.commit()
        return 1

    result = await backfill.execute_backfill(
        coin="btc",
        interval="5m",
        start_ts=BASE_TS,
        end_ts=BASE_TS + 3 * STEP,
        session_factory_fn=sessionmaker,
        ingest_fn=fake_ingest,
    )

    assert result.completed is True
    assert result.gaps_fixed == 1
    assert result.candles_added == 1
    assert result.remaining_gaps is None


@pytest.mark.asyncio
async def test_execute_backfill_reports_remaining(monkeypatch, sessionmaker):
    timestamps = [BASE_TS, BASE_TS + 2 * STEP]
    await _seed(sessionmaker, timestamps)

    async def empty_ingest(session, coin, interval, start_ts, end_ts):
        await session.commit()
        return 0

    result = await backfill.execute_backfill(
        coin="btc",
        interval="5m",
        start_ts=BASE_TS,
        end_ts=BASE_TS + 3 * STEP,
        session_factory_fn=sessionmaker,
        ingest_fn=empty_ingest,
        max_gaps=1,
    )

    assert result.completed is False
    assert result.gaps_fixed == 0
    assert result.remaining_gaps is not None
