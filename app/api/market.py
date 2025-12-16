from fastapi import APIRouter
from app.services.coingecko import fetch_raw_market_data


router = APIRouter(prefix="/market", tags=["market"])

@router.get("/raw")
async def get_raw_market_data():
    return await fetch_raw_market_data()
