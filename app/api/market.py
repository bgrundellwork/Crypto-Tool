from fastapi import APIRouter

from app.services.coingecko import fetch_raw_market_data
from app.schemas.market import MarketSummary
from app.utils.cache import get_cache, set_cache
from app.db.session import SessionLocal
from app.db.models import MarketSnapshot

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
    Cleaned + validated market data with caching + DB persistence.
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

    #  4️ WRITE TO DATABASE (THIS WAS MISSING)
    async with SessionLocal() as session:
        for coin in summary:
            snapshot = MarketSnapshot(
                coin_id=coin.id,
                price=coin.current_price,
                market_cap=coin.market_cap,
                volume=coin.total_volume,
            )
            session.add(snapshot)

        await session.commit()

    # 5️⃣ Store cleaned data in cache
    set_cache(cache_key, summary)

    return summary


from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.models import MarketSnapshot

@router.get("/history")
async def get_market_history(coin: str):
    async with SessionLocal() as session:
        result = await session.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.coin_id == coin)
            .order_by(MarketSnapshot.timestamp.desc())
            .limit(100)
        )
        rows = result.scalars().all()

    return rows
