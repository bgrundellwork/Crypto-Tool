# app/scripts/backfill.py
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from app.db.invariants import verify_candle_invariants
from app.db.session import engine, session_factory
from app.services.completeness import DataIncompleteError, ensure_no_gaps, generate_gap_report
from app.services.ingestion.candles_ingestion import ingest_range


MAX_LOOKBACK_DAYS = int(os.getenv("BACKFILL_MAX_DAYS", "30"))
MAX_GAPS_PER_RUN = int(os.getenv("BACKFILL_MAX_GAPS", "100"))
MAX_CANDLES_PER_RUN = int(os.getenv("BACKFILL_MAX_CANDLES", "10000"))


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ts_meta(dt: datetime) -> Dict[str, int | str]:
    dt = _ensure_utc(dt)
    return {
        "ts_unix": int(dt.timestamp()),
        "ts_iso": dt.isoformat().replace("+00:00", "Z"),
    }


@dataclass
class BackfillResult:
    coin: str
    interval: str
    start_ts: datetime
    end_ts: datetime
    gaps_fixed: int = 0
    candles_added: int = 0
    completed: bool = False
    remaining_gaps: Optional[Dict[str, Any]] = None
    caps_hit: Dict[str, bool] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coin": self.coin,
            "interval": self.interval,
            "start": _ts_meta(self.start_ts),
            "end": _ts_meta(self.end_ts),
            "gaps_fixed": self.gaps_fixed,
            "candles_added": self.candles_added,
            "completed": self.completed,
            "remaining_gaps": self.remaining_gaps,
            "caps_hit": self.caps_hit or {"window_limit": False, "gap_limit": False, "candle_limit": False},
            "error": self.error,
        }


async def _fill_gap_segment(
    *,
    coin: str,
    interval: str,
    gap_start: datetime,
    gap_end: datetime,
    ingest_fn,
    session_factory_fn,
) -> int:
    async with session_factory_fn() as session:
        inserted = await ingest_fn(
            session=session,
            coin=coin,
            interval=interval,
            start_ts=gap_start,
            end_ts=gap_end,
        )
        await verify_candle_invariants(session)
    return inserted


async def execute_backfill(
    *,
    coin: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
    max_gaps: int = MAX_GAPS_PER_RUN,
    max_candles: int = MAX_CANDLES_PER_RUN,
    session_factory_fn: Callable[[], Any] = session_factory,
    ingest_fn: Callable[..., Any] = ingest_range,
) -> BackfillResult:
    start_ts = _ensure_utc(start_ts)
    end_ts = _ensure_utc(end_ts)

    caps_hit = {"window_limit": False, "gap_limit": False, "candle_limit": False}
    max_window = timedelta(days=MAX_LOOKBACK_DAYS)
    requested_span = end_ts - start_ts
    if requested_span > max_window:
        start_ts = end_ts - max_window
        caps_hit["window_limit"] = True

    async with session_factory_fn() as session:
        current_report = await generate_gap_report(
            session,
            coin=coin,
            interval=interval,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    if not current_report.gaps_found:
        return BackfillResult(
            coin=coin,
            interval=interval,
            start_ts=start_ts,
            end_ts=end_ts,
            completed=True,
            caps_hit=caps_hit,
        )

    gaps_fixed = 0
    candles_added = 0
    iterations = 0

    while current_report.gaps and iterations < max_gaps and candles_added < max_candles:
        gap = current_report.gaps[0]
        remaining_capacity = max_candles - candles_added
        if remaining_capacity <= 0:
            break

        inserted = await _fill_gap_segment(
            coin=coin,
            interval=interval,
            gap_start=gap.start,
            gap_end=gap.end,
            ingest_fn=ingest_fn,
            session_factory_fn=session_factory_fn,
        )

        if inserted == 0:
            break

        candles_added += inserted
        iterations += 1

        async with session_factory_fn() as session:
            gap_report = await generate_gap_report(
                session,
                coin=coin,
                interval=interval,
                start_ts=gap.start,
                end_ts=gap.end,
            )
        if not gap_report.gaps_found:
            gaps_fixed += 1

        async with session_factory_fn() as session:
            updated_report = await generate_gap_report(
                session,
                coin=coin,
                interval=interval,
                start_ts=start_ts,
                end_ts=end_ts,
            )

        if len(updated_report.gaps) >= len(current_report.gaps):
            current_report = updated_report
            break

        current_report = updated_report

    if current_report.gaps and iterations >= max_gaps:
        caps_hit["gap_limit"] = True
    if current_report.gaps and candles_added >= max_candles:
        caps_hit["candle_limit"] = True

    async with session_factory_fn() as session:
        try:
            await verify_candle_invariants(session)
        except AssertionError as exc:
            return BackfillResult(
                coin=coin,
                interval=interval,
                start_ts=start_ts,
                end_ts=end_ts,
                gaps_fixed=gaps_fixed,
                candles_added=candles_added,
                completed=False,
                remaining_gaps=current_report.to_dict(),
                caps_hit=caps_hit,
                error=str(exc),
            )

    async with session_factory_fn() as session:
        try:
            await ensure_no_gaps(
                session,
                coin=coin,
                interval=interval,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            completed = True
            remaining = None
        except DataIncompleteError as err:
            completed = False
            remaining = err.report.to_dict()

    return BackfillResult(
        coin=coin,
        interval=interval,
        start_ts=start_ts,
        end_ts=end_ts,
        gaps_fixed=gaps_fixed,
        candles_added=candles_added,
        completed=completed,
        remaining_gaps=remaining,
        caps_hit=caps_hit,
    )


def _parse_datetime(value: str) -> datetime:
    return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _determine_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if args.days is not None:
        end = now
        start = now - timedelta(days=args.days)
        return start, end
    if not args.start or not args.end:
        raise SystemExit("Use either --days N OR --start <ISO8601> --end <ISO8601>")
    return _parse_datetime(args.start), _parse_datetime(args.end)


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled candle backfill")
    parser.add_argument("--coin", required=True)
    parser.add_argument("--interval", required=True)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args()

    start_ts, end_ts = _determine_range(args)

    try:
        result = asyncio.run(
            execute_backfill(
                coin=args.coin,
                interval=args.interval,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        )
        print(json.dumps(result.to_dict()))
        code = 0 if result.completed else 1
        raise SystemExit(code)
    except SystemExit:
        raise
    except Exception as exc:
        failure = BackfillResult(
            coin=args.coin,
            interval=args.interval,
            start_ts=start_ts,
            end_ts=end_ts,
            caps_hit={"window_limit": False, "gap_limit": False, "candle_limit": False},
            error=str(exc),
        )
        print(json.dumps(failure.to_dict()))
        raise SystemExit(1)
    finally:
        try:
            asyncio.run(engine.dispose())
        except Exception:
            pass


if __name__ == "__main__":
    main()
