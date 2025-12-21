from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ingestion.gap_detector import get_existing_candle_times, detect_gaps
from app.utils.intervals import get_interval_seconds


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ts_meta(dt: datetime) -> dict[str, int | str]:
    dt = _utc(dt)
    return {
        "ts_unix": int(dt.timestamp()),
        "ts_iso": dt.isoformat().replace("+00:00", "Z"),
    }


@dataclass
class GapDetail:
    start: datetime
    end: datetime
    missing_candles: int

    def to_dict(self) -> dict[str, int | str]:
        data = {
            **{f"start_{k}": v for k, v in _ts_meta(self.start).items()},
            **{f"end_{k}": v for k, v in _ts_meta(self.end).items()},
            "missing_candles": self.missing_candles,
        }
        return data


@dataclass
class GapReport:
    coin: str
    interval: str
    start_ts: datetime
    end_ts: datetime
    gaps: List[GapDetail]

    @property
    def gaps_found(self) -> bool:
        return bool(self.gaps)

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def total_missing_candles(self) -> int:
        return sum(g.missing_candles for g in self.gaps)

    @property
    def first_gap(self) -> GapDetail | None:
        return self.gaps[0] if self.gaps else None

    @property
    def last_gap(self) -> GapDetail | None:
        return self.gaps[-1] if self.gaps else None

    def to_dict(self) -> dict[str, object]:
        payload = {
            "coin": self.coin,
            "interval": self.interval,
            "start": _ts_meta(self.start_ts),
            "end": _ts_meta(self.end_ts),
            "gaps_found": self.gaps_found,
            "gap_count": self.gap_count,
            "total_missing_candles": self.total_missing_candles,
            "gaps": [g.to_dict() for g in self.gaps],
        }
        if self.first_gap:
            payload["first_gap"] = self.first_gap.to_dict()
        if self.last_gap and (self.last_gap is not self.first_gap):
            payload["last_gap"] = self.last_gap.to_dict()
        return payload


class DataIncompleteError(RuntimeError):
    def __init__(self, report: GapReport):
        super().__init__("Data completeness check failed")
        self.report = report


async def generate_gap_report(
    session: AsyncSession,
    *,
    coin: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
) -> GapReport:
    interval_seconds = get_interval_seconds(interval)
    start_ts = _utc(start_ts)
    end_ts = _utc(end_ts)

    existing = await get_existing_candle_times(session, coin, interval, start_ts, end_ts)
    gaps = detect_gaps(existing, interval, start_ts, end_ts)

    details: List[GapDetail] = []
    for gap in gaps:
        missing = int((gap.end - gap.start).total_seconds() / interval_seconds)
        details.append(
            GapDetail(
                start=gap.start,
                end=gap.end,
                missing_candles=missing,
            )
        )

    return GapReport(
        coin=coin,
        interval=interval,
        start_ts=start_ts,
        end_ts=end_ts,
        gaps=details,
    )


async def ensure_no_gaps(
    session: AsyncSession,
    *,
    coin: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
) -> GapReport:
    report = await generate_gap_report(
        session,
        coin=coin,
        interval=interval,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    if report.gaps_found:
        raise DataIncompleteError(report)
    return report
