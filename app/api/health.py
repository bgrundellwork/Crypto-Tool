# app/api/health.py
import time
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.db.session import engine

router = APIRouter(tags=["health"])


def _normalize_ts(value: Any) -> Tuple[Optional[int], Optional[str]]:
    """
    Returns (unix_seconds, iso_z) from a DB timestamp value.
    Assumes naive datetimes/strings are UTC.
    """
    if value is None:
        return None, None

    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        return int(dt.timestamp()), dt.isoformat().replace("+00:00", "Z")

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return int(dt.timestamp()), dt.isoformat().replace("+00:00", "Z")

    if isinstance(value, str):
        # Handles: "2025-12-17 17:35:00.000000" and ISO-like strings
        s = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None, None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        return int(dt.timestamp()), dt.isoformat().replace("+00:00", "Z")

    return None, None


@router.get("/live")
async def live():
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response):
    t0 = time.perf_counter()
    checks = {}
    ok = True

    # DB + candles
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            checks["db"] = {"ok": True}

            result = await conn.execute(
                text(
                    """
                    SELECT coin, interval, ts
                    FROM candles
                    ORDER BY ts DESC
                    LIMIT 1
                    """
                )
            )
            row = result.mappings().first()
            latest = dict(row) if row else None

            if latest and "ts" in latest:
                ts_unix, ts_iso = _normalize_ts(latest["ts"])
                latest["ts_unix"] = ts_unix
                latest["ts_iso"] = ts_iso

            checks["candles"] = {"ok": True, "latest": latest}

    except Exception:
        ok = False
        checks["db"] = {"ok": False}
        checks["candles"] = {"ok": False}

    # Scheduler (always reported)
    sch = getattr(request.app.state, "scheduler", "missing")

    if sch == "missing":
        checks["scheduler"] = {"ok": False, "reason": "app.state.scheduler not set"}
        ok = False
    elif sch is None:
        checks["scheduler"] = {"ok": False, "reason": "scheduler not started (None) or start_scheduler() returned None"}
        ok = False
    else:
        if hasattr(sch, "info"):
            s_info = sch.info()
            checks["scheduler"] = s_info
            if not bool(s_info.get("ok", False)):
                ok = False
        else:
            checks["scheduler"] = {"ok": True, "type": type(sch).__name__}

    duration_ms = int((time.perf_counter() - t0) * 1000)

    body = {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "duration_ms": duration_ms,
    }

    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return body


@router.get("/health")
async def health(request: Request, response: Response):
    return await ready(request, response)
