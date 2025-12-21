from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import backtest as backtest_module
from app.db import session as db_session
from app.db.models import Candle
from app.db.session import Base
from app.services.completeness import (
    DataIncompleteError,
    ensure_no_gaps,
    generate_gap_report,
)


BASE_TS = datetime(2023, 1, 1, tzinfo=timezone.utc)
INTERVAL = "5m"
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


async def _insert_candles(sessionmaker, timestamps):
    async with sessionmaker() as session:
        session.add_all(
            [
                Candle(
                    coin="btc",
                    interval=INTERVAL,
                    ts=ts,
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    volume=1.0,
                )
                for ts in timestamps
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_ensure_no_gaps_detects_mid_series_gap(sessionmaker):
    timestamps = [BASE_TS, BASE_TS + 2 * STEP, BASE_TS + 3 * STEP]
    await _insert_candles(sessionmaker, timestamps)

    async with sessionmaker() as session:
        with pytest.raises(DataIncompleteError) as excinfo:
            await ensure_no_gaps(
                session,
                coin="btc",
                interval=INTERVAL,
                start_ts=BASE_TS,
                end_ts=BASE_TS + 4 * STEP,
            )
    report = excinfo.value.report
    assert report.coin == "btc"
    assert report.interval == INTERVAL
    assert report.gaps_found is True
    assert report.gap_count == 1
    assert report.total_missing_candles == 1
    assert report.first_gap.start == BASE_TS + STEP
    assert report.first_gap.end == BASE_TS + 2 * STEP


@pytest.mark.asyncio
async def test_ensure_no_gaps_passes_complete_series(sessionmaker):
    timestamps = [BASE_TS + i * STEP for i in range(4)]
    await _insert_candles(sessionmaker, timestamps)
    async with sessionmaker() as session:
        report = await ensure_no_gaps(
            session,
            coin="btc",
            interval=INTERVAL,
            start_ts=BASE_TS,
            end_ts=BASE_TS + 4 * STEP,
        )
    assert report.gaps_found is False
    assert report.gap_count == 0


@pytest.mark.asyncio
async def test_gap_report_captures_start_gap(sessionmaker):
    timestamps = [BASE_TS + STEP, BASE_TS + 2 * STEP]
    await _insert_candles(sessionmaker, timestamps)

    async with sessionmaker() as session:
        report = await generate_gap_report(
            session,
            coin="btc",
            interval=INTERVAL,
            start_ts=BASE_TS,
            end_ts=BASE_TS + 3 * STEP,
        )

    assert report.gap_count == 1
    assert report.gaps_found is True
    assert report.coin == "btc"
    assert report.interval == INTERVAL
    assert report.first_gap.start == BASE_TS
    assert report.first_gap.end == BASE_TS + STEP


@pytest.mark.asyncio
async def test_gap_report_detects_multiple_gaps(sessionmaker):
    timestamps = [
        BASE_TS,
        BASE_TS + STEP,
        BASE_TS + 4 * STEP,
    ]
    await _insert_candles(sessionmaker, timestamps)

    async with sessionmaker() as session:
        report = await generate_gap_report(
            session,
            coin="btc",
            interval=INTERVAL,
            start_ts=BASE_TS,
            end_ts=BASE_TS + 6 * STEP,
        )

    assert report.gap_count == 2
    assert report.gaps_found is True
    assert report.first_gap.start == BASE_TS + 2 * STEP
    assert report.first_gap.end == BASE_TS + 4 * STEP
    assert report.last_gap.start == BASE_TS + 5 * STEP
    assert report.total_missing_candles == 3


def test_backtest_endpoint_blocks_incomplete_data(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    Session = async_sessionmaker(engine, expire_on_commit=False)

    def _session_factory():
        return Session()

    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr(db_session, "session_factory", _session_factory)
    monkeypatch.setattr(backtest_module, "session_factory", _session_factory)

    async def _seed(values):
        async with Session() as session:
            session.add_all(values)
            await session.commit()

    base = BASE_TS
    gap_candles = [
        Candle(coin="btc", interval=INTERVAL, ts=base, open=1, high=1, low=1, close=1, volume=1),
        Candle(
            coin="btc",
            interval=INTERVAL,
            ts=base + 2 * STEP,
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        ),
    ]
    asyncio.run(_seed(gap_candles))

    app = FastAPI()
    app.include_router(backtest_module.router)
    client = TestClient(app)

    payload = {
        "coin": "btc",
        "interval": INTERVAL,
        "start_ts": base.isoformat(),
        "end_ts": (base + 3 * STEP).isoformat(),
    }

    resp = client.post("/backtest/run", json=payload)
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "data_incomplete"
    report = body["error"]["details"]["gap_report"]
    assert report["gaps_found"] is True
    assert report["gap_count"] >= 1

    fill_candle = Candle(
        coin="btc",
        interval=INTERVAL,
        ts=base + STEP,
        open=1,
        high=1,
        low=1,
        close=1,
        volume=1,
    )
    asyncio.run(_seed([fill_candle]))

    resp_after = client.post("/backtest/run", json=payload)
    assert resp_after.status_code != 409

    asyncio.run(engine.dispose())
