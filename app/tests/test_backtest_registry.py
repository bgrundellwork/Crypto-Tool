from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import backtest as backtest_module
from app.api.registry import router as registry_router
from app.db import session as db_session
from app.db.models import Base, Candle


INTERVAL = "5m"
STEP = timedelta(minutes=5)
BASE_TS = datetime(2023, 1, 1, tzinfo=timezone.utc)


class _DummyEnsure:
    async def __call__(self, *_, **__):
        return None


@pytest.fixture()
def registry_app(monkeypatch):
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
    monkeypatch.setattr(backtest_module, "session_factory", _factory)

    async def fake_fetch(session, **kwargs):
        async with Session() as db:
            result = await db.execute(
                select(Candle)
                .where(
                    Candle.coin == kwargs["coin"],
                    Candle.interval == kwargs["interval"],
                )
                .order_by(Candle.ts)
            )
            rows = result.scalars().all()
            return [
                {
                    "timestamp": row.ts,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in rows
            ]

    monkeypatch.setattr(backtest_module, "fetch_candles_from_db", fake_fetch)
    monkeypatch.setattr(backtest_module, "ensure_no_gaps", _DummyEnsure())

    app = FastAPI()
    app.include_router(backtest_module.router)
    app.include_router(registry_router)
    client = TestClient(app)

    yield client, Session

    asyncio.run(engine.dispose())


async def _seed_session(sessionmaker, candles=200):
    async with sessionmaker() as session:
        session.add_all(
            [
                Candle(
                    coin="btc",
                    interval=INTERVAL,
                    ts=BASE_TS + STEP * i,
                    open=100 + i,
                    high=101 + i,
                    low=99 + i,
                    close=100.5 + i,
                    volume=10 + i,
                )
                for i in range(candles)
            ]
        )
        await session.commit()


def test_backtest_run_persists_and_listed(registry_app, monkeypatch):
    client, Session = registry_app
    asyncio.run(_seed_session(Session, 220))

    async def fake_backtest(**kwargs):
        return {
            "status": "ok",
            "initial_capital": 1000.0,
            "final_capital": 1200.0,
            "total_return_pct": 20.0,
            "max_drawdown_pct": 5.0,
            "trades": 10,
            "win_rate_pct": 60.0,
            "equity_curve": [1000, 1100, 1200],
            "trade_list": [
                {"side": "long", "entry_ts": BASE_TS.isoformat(), "exit_ts": (BASE_TS + STEP).isoformat(), "pnl_pct": 5.0}
            ],
        }

    monkeypatch.setattr(backtest_module, "run_backtest_on_candles", fake_backtest)

    payload = {
        "coin": "btc",
        "interval": INTERVAL,
        "code_hash": "abc123",
    }
    resp = client.post("/backtest/run", json=payload)
    assert resp.status_code == 200
    run_resp = resp.json()
    assert run_resp["run_id"]

    resp = client.get("/registry/backtests")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == run_resp["run_id"]

    resp = client.get(f"/registry/backtests/{run_resp['run_id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["summary"]["total_return_pct"] == 20.0
    assert detail["inputs"]["coin"] == "btc"


def test_diff_endpoint(registry_app, monkeypatch):
    client, Session = registry_app
    asyncio.run(_seed_session(Session, 220))

    async def fake_backtest(**kwargs):
        base = kwargs["initial_capital"]
        return {
            "status": "ok",
            "initial_capital": base,
            "final_capital": base * 1.1,
            "total_return_pct": 10.0,
            "max_drawdown_pct": 2.0,
            "trades": 2,
            "win_rate_pct": 50.0,
            "equity_curve": [base, base * 1.05, base * 1.1],
            "trade_list": [],
        }

    monkeypatch.setattr(backtest_module, "run_backtest_on_candles", fake_backtest)

    payload = {"coin": "btc", "interval": INTERVAL, "code_hash": "abc123", "initial_capital": 1000}
    resp = client.post("/backtest/run", json=payload)
    assert resp.status_code == 200
    run_a = resp.json()["run_id"]

    payload["initial_capital"] = 2000
    resp = client.post("/backtest/run", json=payload)
    run_b = resp.json()["run_id"]

    resp = client.post("/registry/backtests/diff", json={"run_a": run_a, "run_b": run_b})
    assert resp.status_code == 200
    diff = resp.json()
    assert "initial_capital" in diff["inputs_diff"]
    assert diff["run_a"] == run_a
    assert diff["run_b"] == run_b
