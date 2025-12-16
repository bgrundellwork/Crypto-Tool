"""Helpers for interacting with the public CoinGecko API."""

from typing import Any

import httpx
from fastapi import HTTPException


COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"


async def fetch_raw_market_data(
    vs_currency: str = "usd",
    order: str = "market_cap_desc",
    per_page: int = 10,
    page: int = 1,
    sparkline: bool = False,
) -> list[dict[str, Any]]:
    """Return the raw CoinGecko market data with a small, documented payload."""

    params = {
        "vs_currency": vs_currency,
        "order": order,
        "per_page": per_page,
        "page": page,
        "sparkline": str(sparkline).lower(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(COINGECKO_URL, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:  # pragma: no cover - exercised via API tests
        raise HTTPException(status_code=502, detail="Unable to reach CoinGecko") from exc
