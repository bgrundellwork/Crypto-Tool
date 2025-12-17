from fastapi import FastAPI
import asyncio

# Routers
from app.api.market import router as market_router
from app.api.backtest import router as backtest_router

# Database
from app.db.session import engine, Base

# Services
from app.services.coingecko import fetch_raw_market_data
from app.services.market_storage import store_market_snapshots

# Scheduler
from app.jobs.scheduler import start_scheduler

# app/main.py (only the relevant bits)
from app.db.bootstrap import ensure_db_primitives
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.config.settings import get_settings

@app.on_event("startup")
async def on_startup():
    await ensure_db_primitives()
    # keep your existing startup logic here...
    if get_settings().INGEST_ENABLED:
        start_scheduler()

@app.on_event("shutdown")
async def on_shutdown():
    # keep your existing shutdown logic here...
    await stop_scheduler()



app = FastAPI(title="Crypto Market API")


# Register routers
app.include_router(market_router)
app.include_router(backtest_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Crypto Boom!"}


async def market_snapshot_loop():
    while True:
        try:
            data = await fetch_raw_market_data()
            await store_market_snapshots(data)
            print("✅ Market snapshot stored")
        except Exception as e:
            print("❌ Snapshot error:", e)

        await asyncio.sleep(60)


@app.on_event("startup")
async def startup() -> None:
    # Create tables if missing (market_snapshots, candles, etc.)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start snapshot collection loop
    asyncio.create_task(market_snapshot_loop())

    # Start candle ingestion scheduler
    start_scheduler()
