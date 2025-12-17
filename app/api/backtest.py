from datetime import datetime
from fastapi import APIRouter

from app.config.timeframes import TIMEFRAME_PROFILES
from app.services.candles import get_candles
from app.services.backtest_engine import run_backtest_on_candles

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run")
async def run_backtest(
    coin: str,
    interval: str = "15m",
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    initial_capital: float = 1000.0,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
    allow_low_conviction: bool = False,
):
    profile = TIMEFRAME_PROFILES.get(interval)
    if not profile:
        return {"error": "Unsupported interval", "supported": list(TIMEFRAME_PROFILES.keys())}

    candles = await get_candles(coin, interval, start_ts=start_ts, end_ts=end_ts)

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

    return result
