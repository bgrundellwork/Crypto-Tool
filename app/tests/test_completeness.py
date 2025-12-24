from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import backtest as backtest_module
from app.db import session as db_session
from app.db.models import Candle
from app.db.session import Base
from app.services.completeness import DataIncompleteError, ensure_no_gaps, generate_gap_report
from app.utils.intervals import get_interval_seconds

INTERVAL = "5m"
STEP_SECONDS = get_interval_seconds(INTERVAL)
BASE_TS = datetime(2023, 11, 14, 22, 10, tzinfo=timezone.utc)


def _ts(idx: int) -> datetime:
    return BASE_TS + timedelta(seconds=idx * STEP_SECONDS)


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


async def _seed(sessionmaker, offsets: list[int]) -> None:
    async with sessionmaker() as session:
        session.add_all(
            [
                Candle(
                    coin="btc",
                    interval=INTERVAL,
                    ts=_ts(offset),
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    volume=1.0,
                )
                for offset in offsets
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_ensure_no_gaps_passes_on_contiguous_series(sessionmaker):
    await _seed(sessionmaker, [0, 1, 2, 3])
    async with sessionmaker() as session:
        report = await ensure_no_gaps(
            session,
            coin="btc",
            interval=INTERVAL,
            start_ts=_ts(0),
            end_ts=_ts(4),
        )
    assert report.gaps_found is False
    assert report.gap_count == 0


@pytest.mark.asyncio
async def test_ensure_no_gaps_raises_and_reports_first_last_gap(sessionmaker):
    await _seed(sessionmaker, [0, 1, 3, 4])
    async with sessionmaker() as session:
        with pytest.raises(DataIncompleteError) as excinfo:
            await ensure_no_gaps(
                session,
                coin="btc",
                interval=INTERVAL,
                start_ts=_ts(0),
                end_ts=_ts(5),
            )
    report = excinfo.value.report
    assert report.gaps_found is True
    assert report.gap_count == 1
    assert report.first_gap.start == _ts(2)
    assert report.first_gap.end == _ts(3)
    assert report.total_missing_candles == 1


@pytest.mark.asyncio
async def test_gap_detector_handles_start_and_end_gaps(sessionmaker):
    await _seed(sessionmaker, [1, 2, 3])
    async with sessionmaker() as session:
        report = await generate_gap_report(
            session,
            coin="btc",
            interval=INTERVAL,
            start_ts=_ts(0),
            end_ts=_ts(5),
        )
    assert report.gap_count == 2
    assert report.first_gap.start == _ts(0)
    assert report.first_gap.end == _ts(1)
    assert report.last_gap.start == _ts(4)
    assert report.last_gap.end == _ts(5)


def test_backtest_endpoint_blocks_and_unblocks_on_gap_fill(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    Session = async_sessionmaker(engine, expire_on_commit=False)

    def _factory():
        return Session()

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr(db_session, "session_factory", _factory)
    monkeypatch.setattr(backtest_module, "session_factory", _factory)

    async def _seed_gap():
        async with Session() as session:
            session.add_all(
                [
                    Candle(coin="btc", interval=INTERVAL, ts=_ts(0), open=1, high=1, low=1, close=1, volume=1),
                    Candle(coin="btc", interval=INTERVAL, ts=_ts(2), open=1, high=1, low=1, close=1, volume=1),
                ]
            )
            await session.commit()

    asyncio.run(_seed_gap())

    app = FastAPI()
    app.include_router(backtest_module.router)
    client = TestClient(app)

    payload = {
        "coin": "btc",
        "interval": INTERVAL,
        "start_ts": _ts(0).isoformat(),
        "end_ts": _ts(3).isoformat(),
    }

    resp = client.post("/backtest/run", json=payload)
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "data_incomplete"
    assert error["details"]["gap_report"]["gaps_found"] is True

    async def _fill():
        async with Session() as session:
            session.add(Candle(coin="btc", interval=INTERVAL, ts=_ts(1), open=1, high=1, low=1, close=1, volume=1))
            await session.commit()

    asyncio.run(_fill())

    resp_after = client.post("/backtest/run", json=payload)
    assert resp_after.status_code != 409
    asyncio.run(engine.dispose())
