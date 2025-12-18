# app/main.py
from __future__ import annotations

from fastapi import FastAPI

from app.api.market import router as market_router
from app.api.backtest import router as backtest_router
from app.api.health import router as health_router

from app.config.settings import get_settings
from app.db.session import engine, Base
from app.db.bootstrap import ensure_db_primitives

from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.jobs.snapshot_collector import start_snapshot_collector, stop_snapshot_collector


app = FastAPI(title="Crypto Market API")

# Routers
app.include_router(health_router)
app.include_router(market_router)
app.include_router(backtest_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Crypto Boom!"}


@app.on_event("startup")
async def on_startup() -> None:
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure indexes/uniques (best-effort)
    await ensure_db_primitives()

    settings = get_settings()  # ✅ this is the key fix (no more NameError: s)

    # Start snapshot collector (raw data spine)
    if settings.SNAPSHOT_ENABLED:
        start_snapshot_collector()

    # Start candle scheduler (derived data spine)
    if settings.INGEST_ENABLED:
        app.state.scheduler = start_scheduler()  # ✅ allows /ready to see scheduler
    else:
        app.state.scheduler = None


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await stop_scheduler()
    app.state.scheduler = None
    await stop_snapshot_collector()
