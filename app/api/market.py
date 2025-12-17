from fastapi import APIRouter
from sqlalchemy import select

# Services
from app.services.coingecko import fetch_raw_market_data
from app.services.candles import get_candles
from app.services.ema import calculate_ema
from app.services.atr import calculate_atr
from app.services.zscore import calculate_zscore, closes_to_returns
from app.services.regime import classify_regime
from app.services.vwap import calculate_vwap
from app.services.signal_engine import compute_signal
from app.services.vov import calculate_vov_from_atr, classify_vov
from app.config.timeframes import TIMEFRAME_PROFILES



# Schemas
from app.schemas.market import MarketSummary

# Database
from app.db.session import SessionLocal
from app.db.models import MarketSnapshot

# Utils
from app.utils.cache import get_cache, set_cache



router = APIRouter(prefix="/market", tags=["market"])

CACHE_TTL = 60  # seconds


@router.get("/raw")
async def get_raw_market_data():
    cache_key = "market_raw"
    cached = get_cache(cache_key, CACHE_TTL)
    if cached is not None:
        return cached

    data = await fetch_raw_market_data()
    set_cache(cache_key, data)
    return data


@router.get("/summary", response_model=list[MarketSummary])
async def get_market_summary():
    cache_key = "market_summary"
    cached = get_cache(cache_key, CACHE_TTL)
    if cached is not None:
        return cached

    raw_data = await fetch_raw_market_data()

    summary = [
        MarketSummary(
            id=coin["id"],
            symbol=coin["symbol"],
            name=coin["name"],
            current_price=coin["current_price"],
            market_cap=coin["market_cap"],
            total_volume=coin["total_volume"],
        )
        for coin in raw_data
    ]

    async with SessionLocal() as session:
        for coin in summary:
            session.add(
                MarketSnapshot(
                    coin_id=coin.id,
                    price=coin.current_price,
                    market_cap=coin.market_cap,
                    volume=coin.total_volume,
                )
            )
        await session.commit()

    set_cache(cache_key, summary)
    return summary


@router.get("/history")
async def get_market_history(coin: str):
    async with SessionLocal() as session:
        result = await session.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.coin_id == coin)
            .order_by(MarketSnapshot.timestamp.desc())
            .limit(100)
        )
        return result.scalars().all()


@router.get("/candles")
async def get_market_candles(coin: str, interval: str = "5m"):
    return await get_candles(coin, interval)

@router.get("/ema")
async def get_market_ema(
    coin: str,
    interval: str = "5m",
    period: int = 20,
):
    """
    EMA calculated from candle closes.
    Example: /market/ema?coin=bitcoin&interval=5m&period=20
    """
    candles = await get_candles(coin, interval)

    closes = [c["close"] for c in candles]
    ema_values = calculate_ema(closes, period)

    # Align EMA timestamps with candles
    ema_series = [
        {
            "timestamp": candles[i + period - 1]["timestamp"],
            "ema": ema_values[i],
        }
        for i in range(len(ema_values))
    ]

    return ema_series

@router.get("/atr")
async def get_market_atr(
    coin: str,
    interval: str = "5m",
    period: int = 14,
):
    """
    ATR (volatility) calculated from candles.
    Example: /market/atr?coin=bitcoin&interval=5m&period=14
    """
    candles = await get_candles(coin, interval)

    if len(candles) < period + 1:
        return []

    atr_values = calculate_atr(candles, period)

    atr_series = [
        {
            "timestamp": candles[i + period]["timestamp"],
            "atr": atr_values[i],
        }
        for i in range(len(atr_values))
    ]

    return atr_series

@router.get("/zscore")
async def get_market_zscore(
    coin: str,
    interval: str = "5m",
    window: int = 96,   # 96 * 5m = 8 hours (good default)
):
    """
    Return rolling Z-score of RETURNS (institutional momentum feature).
    Example: /market/zscore?coin=bitcoin&interval=5m&window=96
    """
    candles = await get_candles(coin, interval)

    closes = [c["close"] for c in candles]
    returns = closes_to_returns(closes)

    z = calculate_zscore(returns, window)

    # Align timestamps:
    # returns start at candles[1]
    # z starts at returns[window-1] -> corresponds to candles index = 1 + (window-1) = window
    z_series = [
        {
            "timestamp": candles[i + window]["timestamp"],
            "zscore": z[i],
        }
        for i in range(len(z))
    ]

    return z_series

@router.get("/regime")
async def get_market_regime(
    coin: str,
    interval: str = "5m",
):
    candles = await get_candles(coin, interval)

    closes = [c["close"] for c in candles]

    # EMA
    ema = calculate_ema(closes, 50)[-1]

    # ATR
    atr = calculate_atr(candles, 14)[-1]

    # Z-score
    returns = closes_to_returns(closes)
    z = calculate_zscore(returns, 48)[-1]

    price = closes[-1]

    return classify_regime(
        price=price,
        ema=ema,
        atr=atr,
        zscore=z,
    )

@router.get("/vwap")
async def get_market_vwap(
    coin: str,
    interval: str = "5m",
):
    """
    VWAP (fair value / location).
    Example: /market/vwap?coin=bitcoin&interval=5m
    """
    candles = await get_candles(coin, interval)
    return calculate_vwap(candles)

@router.get("/signal")
async def get_market_signal(
    coin: str,
    interval: str = "15m",
):
    profile = TIMEFRAME_PROFILES.get(interval)

    if not profile:
        return {
            "error": "Unsupported interval",
            "supported": list(TIMEFRAME_PROFILES.keys()),
            "received": interval,
        }

    ema_period = profile["ema"]
    atr_period = profile["atr"]
    z_window = profile["z"]
    vov_window = profile["vov"]

    candles = await get_candles(coin, interval)

    # Guard: ensure enough candles for indicators
    required = max(ema_period, atr_period + 1, z_window + 1) + 5
    if len(candles) < required:
        return {
            "error": "Not enough candle data for requested interval/profile",
            "interval": interval,
            "required_min_candles": required,
            "received": len(candles),
        }

    closes = [c["close"] for c in candles]
    price = closes[-1]

    # EMA
    ema_series = calculate_ema(closes, ema_period)
    ema = ema_series[-1]

    # ATR
    atr_series = calculate_atr(candles, atr_period)
    atr = atr_series[-1]

    # Z-score
    returns = closes_to_returns(closes)
    z_series = calculate_zscore(returns, z_window)
    z = z_series[-1]

    # Regime
    regime = classify_regime(price=price, ema=ema, atr=atr, zscore=z)

    # VWAP (last)
    vwap_series = calculate_vwap(candles)
    vwap = vwap_series[-1]["vwap"]

    # VoV
    vov_value = calculate_vov_from_atr(atr_series, window=vov_window)
    vov_state = "stable"
    if vov_value is not None:
        vov_state = classify_vov(vov_value, atr)

    # Signal engine
    return compute_signal(
        coin=coin,
        interval=interval,
        trend=regime["trend"],
        vol=regime["volatility"],
        momentum=regime["momentum"],
        price=price,
        vwap=vwap,
        atr=atr,
        vov_state=vov_state,
    )
