from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.invariants import verify_candle_invariants
from app.db.models import Candle
from app.db.session import Base


@pytest.mark.asyncio
async def test_verify_candle_invariants_duplicate_raises_on_commit():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        session.add_all(
            [
                Candle(coin="btc", interval="15m", ts=ts, open=1, high=1, low=1, close=1, volume=1),
                Candle(coin="btc", interval="15m", ts=ts, open=2, high=2, low=2, close=2, volume=2),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_verify_candle_invariants_detects_non_monotonic():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        base = datetime(2023, 1, 1, tzinfo=timezone.utc)
        session.add_all(
            [
                Candle(coin="eth", interval="1h", ts=base, open=1, high=1, low=1, close=1, volume=1),
                Candle(
                    coin="eth",
                    interval="1h",
                    ts=base - timedelta(hours=1),
                    open=2,
                    high=2,
                    low=2,
                    close=2,
                    volume=2,
                ),
            ]
        )
        await session.commit()

        findings = await verify_candle_invariants(session, strict=False)
        assert findings["non_monotonic"]
        assert findings["non_monotonic"][0]["coin"] == "eth"

        with pytest.raises(AssertionError):
            await verify_candle_invariants(session, strict=True)
