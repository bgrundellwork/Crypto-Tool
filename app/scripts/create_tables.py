import asyncio

from app.db.session import engine, Base
import app.db.models  # registers MarketSnapshot + Candle


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tables created/verified")


if __name__ == "__main__":
    asyncio.run(main())

