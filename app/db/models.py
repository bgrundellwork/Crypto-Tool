from uuid import uuid4

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, UniqueConstraint, Index
from app.db.session import Base
from app.utils.time import utcnow


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
    timestamp = Column(DateTime(timezone=True), default=utcnow)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("coin", "interval", "ts", name="uq_candles_coin_interval_ts"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(String, nullable=False, default="local")  # derived from your snapshots
    coin = Column(String, nullable=False, index=True)
    interval = Column(String, nullable=False, index=True)

    ts = Column(DateTime(timezone=True), nullable=False, index=True)  # candle open time (UTC)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


Index(
    "ix_candles_coin_interval_ts_desc",
    Candle.coin,
    Candle.interval,
    Candle.ts.desc(),
)


class FeatureRow(Base):
    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint(
            "coin",
            "interval",
            "ts",
            "feature_set",
            "schema_version",
            "data_hash",
            "code_hash",
            name="uq_features_deterministic_key",
        ),
        Index("ix_features_coin_interval_ts_desc", "coin", "interval", "ts"),
        Index("ix_features_feature_set_schema", "feature_set", "schema_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    coin = Column(String, nullable=False, index=True)
    interval = Column(String, nullable=False, index=True)
    ts = Column(DateTime(timezone=True), nullable=False, index=True)
    feature_set = Column(String, nullable=False, default="core_v1")
    schema_version = Column(Integer, nullable=False, default=1)
    params_json = Column(Text, nullable=False)
    values_json = Column(Text, nullable=False)
    data_hash = Column(String, nullable=False)
    code_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        UniqueConstraint("run_hash", name="uq_backtest_runs_run_hash"),
        Index("ix_backtest_runs_created_at", "created_at"),
        Index("ix_backtest_runs_strategy_created", "strategy_name", "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    strategy_name = Column(String, nullable=False, index=True)
    inputs_json = Column(Text, nullable=False)
    summary_json = Column(Text, nullable=False)
    trades_json = Column(Text, nullable=False)
    equity_json = Column(Text, nullable=False)
    code_hash = Column(String, nullable=False, index=True)
    data_hash = Column(String, nullable=False, index=True)
    feature_hash = Column(String, nullable=True)
    run_hash = Column(String, nullable=False, unique=True)
