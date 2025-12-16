from fastapi import FastAPI
import asyncio

from app.api.market import router as market_router
from app.db.session import engine, Base
from app.db import models  # registers tables
from app.services.coingecko import fetch_raw_market_data
from app.services.market_storage import store_market_snapshots

app = FastAPI(title="Crypto Market API")


async def market_snapshot_loop():
    while True:
        try:
            data = await fetch_raw_market_data()
            await store_market_snapshots(data)
            print("✅ Market snapshot stored")
        except Exception as e:
            print("❌ Snapshot error:", e)

        await asyncio.sleep(60)  # run every 60 seconds


@app.on_event("startup")
async def startup() -> None:
    # 1️⃣ Ensure DB tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2️⃣ Start background snapshot loop
    asyncio.create_task(market_snapshot_loop())


app.include_router(market_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Crypto Boom!"}
