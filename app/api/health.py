# app/api/health.py
from __future__ import annotations

import importlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.db.session import engine
from app.utils.readiness import annotate_scheduler_jobs

router = APIRouter(tags=["health"])

APP_STARTED_AT = time.time()


# ----------------------------
# Timestamp normalization
# ----------------------------
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


def _now_meta() -> Dict[str, Any]:
    now_ts = time.time()
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    return {
        "now_ts": now_ts,
        "now_unix": int(now_ts),
        "now_iso": now_dt.isoformat().replace("+00:00", "Z"),
        "uptime_s": int(now_ts - APP_STARTED_AT),
    }


# ----------------------------
# Async DB checks (your engine is AsyncEngine)
# ----------------------------
async def _check_db() -> Dict[str, Any]:
    t0 = time.time()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {
            "ok": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e),
        }


async def _check_candles_latest() -> Dict[str, Any]:
    """
    Confirms candles table readable and returns latest candle ts in unix + iso.
    """
    t0 = time.time()
    try:
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    """
                    SELECT coin, interval, ts, open, high, low, close, volume
                    FROM candles
                    ORDER BY ts DESC
                    LIMIT 1
                    """
                )
            )
            row = res.mappings().first()

        if not row:
            return {
                "ok": False,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": "candles table readable but empty",
            }

        ts_unix, ts_iso = _normalize_ts(row.get("ts"))
        return {
            "ok": True,
            "latency_ms": int((time.time() - t0) * 1000),
            "latest": {
                "coin": row.get("coin"),
                "interval": row.get("interval"),
                "ts_unix": ts_unix,
                "ts_iso": ts_iso,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e),
        }


# ----------------------------
# Scheduler status loader (dynamic)
# ----------------------------
def _try_get_scheduler_status() -> Optional[Dict[str, Any]]:
    """
    Tries common patterns to pull scheduler state from your codebase.

    BEST PRACTICE:
      Expose a function in your scheduler module:
        def get_scheduler_status() -> dict: return SCHEDULER_STATUS
    """
    candidates = [
        # Most common / recommended
        ("app.jobs.scheduler", "get_scheduler_status"),
        ("app.jobs.scheduler", "get_status"),

        # Fallbacks people often use
        ("app.jobs.scheduler", "status"),
        ("app.jobs.scheduler", "scheduler_status"),
        ("app.jobs.scheduler", "SCHEDULER_STATUS"),
        ("app.jobs.scheduler", "SCHEDULER_STATE"),
        ("app.jobs.scheduler", "STATE"),

        # Alternate module names (if you named it differently)
        ("app.jobs.scheduler_service", "get_scheduler_status"),
        ("app.jobs.job_scheduler", "get_scheduler_status"),
        ("app.services.scheduler", "get_scheduler_status"),
        ("app.scheduler", "get_scheduler_status"),
    ]

    for module_name, attr in candidates:
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue

        if not hasattr(mod, attr):
            continue

        obj = getattr(mod, attr)

        try:
            status = obj() if callable(obj) else obj
        except Exception:
            continue

        if isinstance(status, dict):
            return status

    return None


def _normalize_scheduler_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(raw)

    meta = out.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    for k in ("pid", "started_at", "uptime_s"):
        if k in out and k not in meta:
            meta[k] = out.get(k)
    out["meta"] = meta

    if "running" not in out:
        out["running"] = True

    if "per_job" not in out:
        out["per_job"] = {}

    return out


def _check_scheduler() -> Dict[str, Any]:
    t0 = time.time()
    raw = _try_get_scheduler_status()
    if raw is None:
        return {
            "ok": False,
            "running": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": "scheduler status unavailable (no accessor found)",
            "per_job": {},
            "meta": {},
        }

    sched = _normalize_scheduler_payload(raw)
    sched["latency_ms"] = int((time.time() - t0) * 1000)

    if "ok" not in sched:
        sched["ok"] = True

    return sched


# ----------------------------
# Payload builder
# ----------------------------
async def build_ready_payload() -> Dict[str, Any]:
    timing = _now_meta()

    db_check = await _check_db()
    candles_check = await _check_candles_latest()
    scheduler_check = _check_scheduler()

    return {
        "status": "ok",
        **timing,
        "checks": {
            "db": db_check,
            "candles": candles_check,
            "scheduler": scheduler_check,
        },
    }


# ----------------------------
# Endpoints
# ----------------------------
@router.get("/live")
async def live():
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response):
    payload = await build_ready_payload()
    checks = payload.get("checks", {})

    degraded_reasons = []

    if not (checks.get("db") or {}).get("ok", False):
        degraded_reasons.append("db_unhealthy")

    if not (checks.get("candles") or {}).get("ok", False):
        degraded_reasons.append("candles_unhealthy")

    scheduler = checks.get("scheduler", {})
    if scheduler and scheduler.get("running"):
        scheduler, stale = annotate_scheduler_jobs(scheduler)
        checks["scheduler"] = scheduler

        if stale:
            degraded_reasons.append("scheduler_stalled_jobs")
            payload["stale_jobs"] = stale
            scheduler["ok"] = False
        else:
            scheduler["ok"] = True
    else:
        # Treat as degraded unless you intentionally run without scheduler
        if scheduler and not scheduler.get("ok", True):
            degraded_reasons.append("scheduler_unavailable")

    if degraded_reasons:
        payload["status"] = "degraded"
        payload["degraded"] = True
        payload["degraded_reasons"] = degraded_reasons
        response.status_code = 503
    else:
        payload["status"] = "ok"
        payload["degraded"] = False
        payload["degraded_reasons"] = []

    payload["checks"] = checks
    return payload


@router.get("/health")
async def health(response: Response):
    # Deep health == readiness here
    return await ready(response)
