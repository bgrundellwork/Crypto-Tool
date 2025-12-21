"""Pydantic models for backtest request/response contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator, model_validator


class BacktestRunRequest(BaseModel):
    """Canonical JSON body for POST /backtest/run."""

    coin: str = Field(..., description="Asset symbol to backtest, e.g. btc")
    interval: str = Field("15m", description="Candle interval such as 5m, 15m, 1h")

    start_ts: Optional[datetime] = Field(
        default=None,
        description="Inclusive start timestamp (ISO8601 or unix seconds).",
    )
    end_ts: Optional[datetime] = Field(
        default=None,
        description="Exclusive end timestamp (ISO8601 or unix seconds).",
    )

    initial_capital: float = Field(1000.0, ge=0.0)
    fee_bps: float = Field(4.0, ge=0.0)
    slippage_bps: float = Field(2.0, ge=0.0)
    allow_low_conviction: bool = Field(False)

    # ---------- Timestamp coercion ----------

    @field_validator("start_ts", "end_ts", mode="before")
    @classmethod
    def coerce_ts(cls, value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None

        if isinstance(value, datetime):
            return cls._ensure_utc(value)

        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)

        if isinstance(value, str):
            normalized = value.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(f"Invalid timestamp value '{value}'") from exc
            return cls._ensure_utc(dt)

        raise TypeError(f"Unsupported timestamp type: {type(value)!r}")

    # ---------- Cross-field validation ----------

    @model_validator(mode="after")
    def validate_range(self) -> "BacktestRunRequest":
        if self.start_ts and self.end_ts and self.start_ts >= self.end_ts:
            raise ValueError("start_ts must be earlier than end_ts")
        return self

    # ---------- Helpers ----------

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

class RequestedRange(BaseModel):
    start_ts_unix: int | None
    end_ts_unix: int | None
    interval: str


class InsufficientDataDetail(BaseModel):
    coin: str
    interval: str
    required_candles: int
    received_candles: int
    required_lookback_seconds: int
    latest_candle_ts_unix: int | None
    latest_candle_ts_iso: str | None
    suggested_start_ts_unix: int | None
    suggested_start_ts_iso: str | None
    requested_range: RequestedRange


class InsufficientDataResponse(BaseModel):
    status: str = "insufficient_data"
    message: str
    detail: InsufficientDataDetail
