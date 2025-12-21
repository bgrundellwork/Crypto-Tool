from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint, Index
from datetime import datetime
from app.db.session import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("coin_id", "timestamp", name="uq_market_snapshots_coin_ts"),
    )

    id = Column(Integer, primary_key=True)
    coin_id = Column(String, index=True)
    price = Column(Float)
    market_cap = Column(Float)
    volume = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("coin", "interval", "ts", name="uq_candles_coin_interval_ts"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(String, nullable=False, default="local")  # derived from your snapshots
    coin = Column(String, nullable=False, index=True)
    interval = Column(String, nullable=False, index=True)

    ts = Column(DateTime, nullable=False, index=True)  # candle open time (UTC)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


Index(
    "ix_candles_coin_interval_ts_desc",
    Candle.coin,
    Candle.interval,
    Candle.ts.desc(),
)
