# app/api/backtest.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config.timeframes import TIMEFRAME_PROFILES
from app.db.session import session_factory
from app.services.candle_reader import fetch_candles_from_db
from app.services.backtest_engine import run_backtest_on_candles
from app.schemas.backtest import (
    BacktestRunRequest,
    InsufficientDataDetail,
    InsufficientDataResponse,
    RequestedRange,
)
from app.services.completeness import ensure_no_gaps, DataIncompleteError
from app.utils.intervals import get_interval_seconds


router = APIRouter(prefix="/backtest", tags=["backtest"])


_REQUEST_FIELDS = frozenset(BacktestRunRequest.__fields__.keys())


def _error_response(
    *,
    code: str,
    message: str,
    status_code: int = 400,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def _normalize_dt(value: datetime | None) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp()), dt.isoformat().replace("+00:00", "Z")


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _required_candle_count(profile: dict[str, int]) -> int:
    return max(
        profile["ema"],
        profile["atr"] + 2,
        profile["z"] + 2,
        profile["vov"] + 2,
    ) + 5


def _insufficient_data_response(
    *,
    coin: str,
    interval: str,
    candles: list[dict[str, Any]],
    required_candles: int,
    required_lookback_seconds: int,
    requested_range: RequestedRange,
) -> JSONResponse:
    latest_ts = candles[-1]["timestamp"] if candles else None
    latest_unix, latest_iso = _normalize_dt(latest_ts)

    suggested_dt = (
        latest_ts - timedelta(seconds=required_lookback_seconds) if latest_ts else None
    )
    suggested_unix, suggested_iso = _normalize_dt(suggested_dt)

    detail = InsufficientDataDetail(
        coin=coin,
        interval=interval,
        required_candles=required_candles,
        received_candles=len(candles),
        required_lookback_seconds=required_lookback_seconds,
        latest_candle_ts_unix=latest_unix,
        latest_candle_ts_iso=latest_iso,
        suggested_start_ts_unix=suggested_unix,
        suggested_start_ts_iso=suggested_iso,
        requested_range=requested_range,
    )

    message = (
        f"Need {required_candles} candles but received {len(candles)}. "
        f"Restart from {suggested_iso or 'an earlier start timestamp'}."
    )

    return JSONResponse(
        status_code=200,
        content=InsufficientDataResponse(message=message, detail=detail).dict(),
    )


def _requested_range(
    *,
    interval: str,
    start_ts: datetime | None,
    end_ts: datetime | None,
) -> RequestedRange:
    start_unix, _ = _normalize_dt(start_ts)
    end_unix, _ = _normalize_dt(end_ts)
    return RequestedRange(
        start_ts_unix=start_unix,
        end_ts_unix=end_unix,
        interval=interval,
    )


def _offending_query_params(params: Iterable[str]) -> list[str]:
    return [key for key in params if key in _REQUEST_FIELDS]


def _derive_range(
    payload: BacktestRunRequest,
    candles: list[dict[str, Any]],
    interval_seconds: int,
) -> tuple[datetime | None, datetime | None]:
    start = payload.start_ts or (candles[0]["timestamp"] if candles else None)
    end = payload.end_ts
    if not end and candles:
        end = candles[-1]["timestamp"] + timedelta(seconds=interval_seconds)
    return _as_utc(start), _as_utc(end)


@router.post("/run")
async def run_backtest(request: Request, payload: BacktestRunRequest):
    offending = _offending_query_params(request.query_params.keys())
    if offending:
        return _error_response(
            code="use_json_body",
            message="Use JSON body for /backtest/run inputs; query params are not supported.",
            details={"query_params": offending},
        )

    profile = TIMEFRAME_PROFILES.get(payload.interval)
    if not profile:
        return _error_response(
            code="invalid_interval",
            message=f"Unsupported interval '{payload.interval}'",
            details={"supported": list(TIMEFRAME_PROFILES.keys())},
        )

    try:
        interval_seconds = get_interval_seconds(payload.interval)
    except ValueError:
        return _error_response(
            code="invalid_interval",
            message=f"Interval mapping missing for '{payload.interval}'",
            details={"supported": list(TIMEFRAME_PROFILES.keys())},
        )

    # ✅ IMPORTANT CHANGE: read candles from DB (not snapshot-derived get_candles)
    async with session_factory() as session:
        candles = await fetch_candles_from_db(
            session,
            coin=payload.coin,
            interval=payload.interval,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
        )
        completeness_start, completeness_end = _derive_range(payload, candles, interval_seconds)
        if completeness_start and completeness_end:
            try:
                await ensure_no_gaps(
                    session,
                    coin=payload.coin,
                    interval=payload.interval,
                    start_ts=completeness_start,
                    end_ts=completeness_end,
                )
            except DataIncompleteError as err:
                return _error_response(
                    code="data_incomplete",
                    message="Requested window contains missing candles; backtest blocked.",
                    status_code=409,
                    details={"gap_report": err.report.to_dict()},
                )

    required_candles = _required_candle_count(profile)
    if len(candles) < required_candles:
        requested_range = _requested_range(
            interval=payload.interval,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
        )
        required_lookback_seconds = required_candles * interval_seconds
        return _insufficient_data_response(
            coin=payload.coin,
            interval=payload.interval,
            candles=candles,
            required_candles=required_candles,
            required_lookback_seconds=required_lookback_seconds,
            requested_range=requested_range,
        )

    result = await run_backtest_on_candles(
        coin=payload.coin,
        interval=payload.interval,
        candles=candles,
        ema_period=profile["ema"],
        atr_period=profile["atr"],
        z_window=profile["z"],
        vov_window=profile["vov"],
        initial_capital=payload.initial_capital,
        fee_bps=payload.fee_bps,
        slippage_bps=payload.slippage_bps,
        allow_low_conviction=payload.allow_low_conviction,
    )

    # helpful debug metadata
    result["coin"] = payload.coin
    result["interval"] = payload.interval
    result["candles_used"] = len(candles)

    return result
