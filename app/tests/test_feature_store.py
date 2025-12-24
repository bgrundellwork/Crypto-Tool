from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api.features import router as features_router
from app.db import session as db_session
from app.db.models import Base, Candle, FeatureRow
from sqlalchemy import select, func


INTERVAL = "5m"
STEP = timedelta(minutes=5)
BASE_TS = datetime(2023, 11, 14, 22, 10, tzinfo=timezone.utc)


@pytest.fixture()
def feature_app(monkeypatch):
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

    app = FastAPI()
    app.include_router(features_router)
    client = TestClient(app)

    yield client, Session

    asyncio.run(engine.dispose())


async def _seed_candles(sessionmaker, n: int = 60):
    async with sessionmaker() as session:
        session.add_all(
            [
                Candle(
                    coin="btc",
                    interval=INTERVAL,
                    ts=BASE_TS + STEP * i,
                    open=100.0 + i,
                    high=101.0 + i,
                    low=99.0 + i,
                    close=100.5 + i,
                    volume=10.0 + i,
                )
                for i in range(n)
            ]
        )
        await session.commit()


def test_materialize_features_caches(feature_app):
    client, Session = feature_app
    asyncio.run(_seed_candles(Session, 80))

    payload = {
        "coin": "btc",
        "interval": INTERVAL,
        "start_ts": BASE_TS.isoformat(),
        "end_ts": (BASE_TS + STEP * 70).isoformat(),
        "code_hash": "abc123",
    }
    resp = client.post("/features/materialize", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["features"], "Features should be produced"
    first_count = len(data["features"])

    resp2 = client.post("/features/materialize", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["features"]) == first_count

    async def _count_rows():
        async with Session() as session:
            result = await session.execute(select(func.count()).select_from(FeatureRow))
            return result.scalar_one()

    total_rows = asyncio.run(_count_rows())
    assert total_rows == first_count


def test_latest_endpoint(feature_app):
    client, Session = feature_app
    asyncio.run(_seed_candles(Session, 120))

    payload = {
        "coin": "btc",
        "interval": INTERVAL,
        "start_ts": BASE_TS.isoformat(),
        "end_ts": (BASE_TS + STEP * 90).isoformat(),
        "code_hash": "abc123",
    }
    resp = client.post("/features/materialize", json=payload)
    assert resp.status_code == 200

    resp = client.get("/features/latest", params={"coin": "btc", "interval": INTERVAL})
    assert resp.status_code == 200
    latest = resp.json()
    assert latest["coin"] == "btc"
    assert latest["interval"] == INTERVAL
    assert "values" in latest
