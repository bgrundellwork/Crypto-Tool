from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./market.db"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

class Base(DeclarativeBase):
    pass


# ✅ For FastAPI routes (optional now, useful soon)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


# ✅ For scheduler jobs (so each job gets a fresh session)
def session_factory():
    return SessionLocal()

