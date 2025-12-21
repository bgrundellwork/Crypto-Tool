from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import backtest as backtest_module
from app.services.completeness import GapDetail, GapReport, DataIncompleteError


class _DummySession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_candles(count: int, interval_minutes: int = 15) -> list[dict[str, float]]:
    base = datetime(2023, 1, 1, tzinfo=timezone.utc)
    candles = []
    for i in range(count):
        ts = base + timedelta(minutes=interval_minutes * i)
        price = 100.0 + i
        candles.append(
            {
                "timestamp": ts,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price + 0.5,
                "volume": 10.0,
            }
        )
    return candles


@pytest.fixture()
def backtest_client(monkeypatch):
    state = {"candles": _make_candles(50)}

    monkeypatch.setattr(backtest_module, "session_factory", lambda: _DummySession())

    async def fake_fetch(session, **kwargs):
        return state["candles"]

    async def fake_backtest(**kwargs):
        return {"status": "ok", "echo": kwargs}

    async def fake_ensure(session, **kwargs):
        return None

    monkeypatch.setattr(backtest_module, "fetch_candles_from_db", fake_fetch)
    monkeypatch.setattr(backtest_module, "run_backtest_on_candles", fake_backtest)
    monkeypatch.setattr(backtest_module, "ensure_no_gaps", fake_ensure)

    app = FastAPI()
    app.include_router(backtest_module.router)
    client = TestClient(app)
    yield client, state


def test_rejects_query_params(backtest_client):
    client, _ = backtest_client
    resp = client.post("/backtest/run?coin=btc", json={"coin": "btc"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "use_json_body"
    assert "coin" in body["error"]["details"]["query_params"]


def test_runs_with_json_body(backtest_client):
    client, state = backtest_client
    state["candles"] = _make_candles(60)
    resp = client.post("/backtest/run", json={"coin": "btc", "interval": "15m"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["coin"] == "btc"
    assert body["interval"] == "15m"
    assert body["candles_used"] == 60


def test_insufficient_data_payload(backtest_client):
    client, state = backtest_client
    state["candles"] = _make_candles(5)
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    resp = client.post(
        "/backtest/run",
        json={
            "coin": "eth",
            "interval": "15m",
            "start_ts": start.isoformat(),
            "end_ts": int(end.timestamp()),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "insufficient_data"
    assert body["detail"]["required_candles"] > body["detail"]["received_candles"]
    assert body["detail"]["requested_range"]["start_ts_unix"] == int(start.timestamp())
    assert body["detail"]["requested_range"]["end_ts_unix"] == int(end.timestamp())
    assert "Need" in body["message"]


def test_backtest_blocks_on_gaps(monkeypatch, backtest_client):
    client, state = backtest_client
    state["candles"] = _make_candles(60)

    report = GapReport(
        coin="btc",
        interval="15m",
        start_ts=state["candles"][0]["timestamp"],
        end_ts=state["candles"][-1]["timestamp"] + timedelta(minutes=15),
        gaps=[GapDetail(start=state["candles"][0]["timestamp"], end=state["candles"][0]["timestamp"] + timedelta(minutes=15), missing_candles=1)],
    )

    async def fake_ensure(session, **kwargs):
        raise DataIncompleteError(report)

    monkeypatch.setattr(backtest_module, "ensure_no_gaps", fake_ensure)

    resp = client.post("/backtest/run", json={"coin": "btc", "interval": "15m"})
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "data_incomplete"
    assert body["error"]["details"]["gap_report"]["gaps_found"] is True
