from fastapi import APIRouter
from app.services.coingecko import fetch_raw_market_data


router = APIRouter(prefix="/market", tags=["market"])

@router.get("/raw")
async def get_raw_market_data():
    return await fetch_raw_market_data()

@router.get("/summary")
async def get_summary():
    raw = await fetch_raw_market_data()
    summary = [
        {
            "id": coin["id"],
            "symbol": coin["symbol"],
            "name": coin["name"],
            "current_price": coin["current_price"],
            "market_cap": coin["market_cap"],
            "total_volume": coin["total_volume"],
        }
        for coin in raw
    ]
    return summary
    
    