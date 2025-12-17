# app/api/backtest.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body

from app.config.timeframes import TIMEFRAME_PROFILES
from app.db.session import session_factory
from app.services.candle_reader import fetch_candles_from_db
from app.services.backtest_engine import run_backtest_on_candles


router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run")
async def run_backtest(
    # ✅ Optional JSON body (so calling {} won’t 422 if you include defaults)
    body: dict[str, Any] | None = Body(default=None),
    # ✅ Backwards compatible query params (if you still call it that way)
    coin: str | None = None,
    interval: str = "15m",
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    initial_capital: float = 1000.0,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
    allow_low_conviction: bool = False,
):
    # Prefer body if provided
    if body:
        coin = body.get("coin", coin)
        interval = body.get("interval", interval)
        start_ts = body.get("start_ts", start_ts)
        end_ts = body.get("end_ts", end_ts)
        initial_capital = float(body.get("initial_capital", initial_capital))
        fee_bps = float(body.get("fee_bps", fee_bps))
        slippage_bps = float(body.get("slippage_bps", slippage_bps))
        allow_low_conviction = bool(body.get("allow_low_conviction", allow_low_conviction))

    if not coin:
        return {"error": "Missing coin. Provide ?coin=... or JSON body {coin: ...}"}

    profile = TIMEFRAME_PROFILES.get(interval)
    if not profile:
        return {"error": "Unsupported interval", "supported": list(TIMEFRAME_PROFILES.keys())}

    # ✅ IMPORTANT CHANGE: read candles from DB (not snapshot-derived get_candles)
    async with session_factory() as session:
        candles = await fetch_candles_from_db(
            session,
            coin=coin,
            interval=interval,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    result = await run_backtest_on_candles(
        coin=coin,
        interval=interval,
        candles=candles,
        ema_period=profile["ema"],
        atr_period=profile["atr"],
        z_window=profile["z"],
        vov_window=profile["vov"],
        initial_capital=initial_capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        allow_low_conviction=allow_low_conviction,
    )

    # helpful debug metadata
    result["coin"] = coin
    result["interval"] = interval
    result["candles_used"] = len(candles)

    return result
