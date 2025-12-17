import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import asyncio

from app.db.session import SessionLocal
from app.services.ingestion.candles_ingestion import ingest_latest


async def main():
    async with SessionLocal() as session:
        n = await ingest_latest(session=session, coin="bitcoin", interval="15m")
        print("✅ inserted/updated candles:", n)


if __name__ == "__main__":
    asyncio.run(main())

