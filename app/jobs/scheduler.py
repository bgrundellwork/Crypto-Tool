# app/jobs/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.session import session_factory
from app.services.ingestion.candles_ingestion import ingest_latest

scheduler = AsyncIOScheduler()

def start_scheduler():
    print("✅ candle scheduler started")  # <-- this prints once on startup

    scheduler.add_job(
        ingest_job,
        trigger=IntervalTrigger(seconds=60),
        id="ingest_bitcoin_15m",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

async def ingest_job():
    print("🕯️ ingest job running")  # <-- this prints every time the job fires
    async with session_factory() as session:
        await ingest_latest(session=session, coin="bitcoin", interval="15m")
