"""Pydantic models for market-related responses."""

from pydantic import BaseModel


class MarketSummary(BaseModel):
    """Small subset of the CoinGecko market payload exposed to clients."""

    id: str
    symbol: str
    name: str
    current_price: float
    market_cap: int
    total_volume: int
