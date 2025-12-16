from fastapi import APIRouter

from app.services.coingecko import fetch_raw_market_data
from app.models.market import MarketSummary
from app.utils.cache import get_cache, set_cache


router = APIRouter(prefix="/market", tags=["market"])


# How long cached data is valid (seconds)
CACHE_TTL = 60  # 1 minute


@router.get("/raw")
async def get_raw_market_data():
    """
    Raw CoinGecko data with caching.
    """
    cache_key = "market_raw"

    # 1️⃣ Try cache first
    cached = get_cache(cache_key, CACHE_TTL)
    if cached is not None:
        return cached

    # 2️⃣ Fetch from CoinGecko
    data = await fetch_raw_market_data()

    # 3️⃣ Store in cache
    set_cache(cache_key, data)

    return data


@router.get("/summary", response_model=list[MarketSummary])
async def get_market_summary():
    """
    Cleaned + validated market data with caching.
    """
    cache_key = "market_summary"

    # 1️⃣ Try cache
    cached = get_cache(cache_key, CACHE_TTL)
    if cached is not None:
        return cached

    # 2️⃣ Fetch raw data
    raw_data = await fetch_raw_market_data()

    # 3️⃣ Clean + validate
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

    # 4️⃣ Store cleaned data in cache
    set_cache(cache_key, summary)

    return summary
