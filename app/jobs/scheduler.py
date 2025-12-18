# app/jobs/scheduler.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config.settings import get_settings
from app.db.session import session_factory

logger = logging.getLogger("crypto_fastapi.scheduler")


# ----------------------------
# timeframe -> seconds mapping
# ----------------------------
def _default_timeframe_seconds() -> Dict[str, int]:
    return {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "1d": 86400,
    }


def timeframe_seconds(tf: str) -> int:
    try:
        from app.config.timeframes import TIMEFRAME_SECONDS  # type: ignore
        return int(TIMEFRAME_SECONDS[tf])
    except Exception:
        pass

    try:
        from app.config.timeframes import TIMEFRAMES  # type: ignore
        if isinstance(TIMEFRAMES, dict) and tf in TIMEFRAMES:
            return int(TIMEFRAMES[tf])
    except Exception:
        pass

    mapping = _default_timeframe_seconds()
    if tf not in mapping:
        raise ValueError(f"Unknown interval/timeframe: {tf}")
    return mapping[tf]


# ----------------------------
# lock file: prevent duplicates under --reload
# ----------------------------
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_lock_pid(lock_path: str) -> Optional[int]:
    try:
        with open(lock_path, "r") as f:
            data = json.load(f)
        return int(data.get("pid", -1))
    except Exception:
        return None


def _acquire_lock(lock_path: str, payload: dict) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        return True
    except FileExistsError:
        pid = _read_lock_pid(lock_path)
        if pid is not None and _pid_alive(pid):
            return False  # active scheduler elsewhere

        # stale lock -> remove and retry once
        try:
            os.remove(lock_path)
        except Exception:
            return False

        return _acquire_lock(lock_path, payload)


def _release_lock(lock_path: str) -> None:
    try:
        os.remove(lock_path)
    except Exception:
        return


# ----------------------------
# timestamp helpers (for info payload)
# ----------------------------
def _iso_z_from_epoch(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _now_epoch() -> float:
    return time.time()


# ----------------------------
# scheduler state + handle
# ----------------------------
@dataclass
class SchedulerState:
    started: bool = False
    stop_event: Optional[asyncio.Event] = None
    tasks: Dict[str, asyncio.Task] = field(default_factory=dict)      # job_id -> task
    locks: Dict[str, asyncio.Lock] = field(default_factory=dict)      # job_id -> lock
    lock_path: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    job_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # job_id -> stats


@dataclass(frozen=True)
class SchedulerHandle:
    """
    Stored in app.state.scheduler so /ready can report scheduler status.
    """
    _state: SchedulerState

    @property
    def running(self) -> bool:
        return bool(self._state.started and self._state.stop_event and not self._state.stop_event.is_set())

    @property
    def jobs(self) -> int:
        return len(self._state.tasks)

    def info(self) -> Dict[str, Any]:
        meta = dict(self._state.meta) if self._state.meta else {}
        started_at = meta.get("started_at")
        started_at_f = float(started_at) if started_at is not None else None

        info: Dict[str, Any] = {
            "ok": self.running,
            "running": self.running,
            "jobs": self.jobs,
            "lock_path": self._state.lock_path,
            "uptime_s": int(_now_epoch() - started_at_f) if started_at_f else None,
            "meta": {
                **meta,
                "started_at_iso": _iso_z_from_epoch(started_at_f),
            },
            "per_job": {},
        }

        # Small, stable per-job health signal
        for job_id, s in self._state.job_stats.items():
            info["per_job"][job_id] = {
                "coin": s.get("coin"),
                "interval": s.get("interval"),
                "schedule_s": s.get("schedule_s"),
                "last_run_ts": s.get("last_run_ts"),
                "last_run_iso": _iso_z_from_epoch(s.get("last_run_ts")),
                "last_success_ts": s.get("last_success_ts"),
                "last_success_iso": _iso_z_from_epoch(s.get("last_success_ts")),
                "last_success_inserted": s.get("last_success_inserted"),
                "last_success_ms": s.get("last_success_ms"),
                "consecutive_failures": s.get("consecutive_failures", 0),
                "last_error_ts": s.get("last_error_ts"),
                "last_error_iso": _iso_z_from_epoch(s.get("last_error_ts")),
                "last_error": s.get("last_error"),
            }

        return info


_state = SchedulerState()


# ----------------------------
# ingestion entrypoint adapter
# ----------------------------
async def _run_ingestion(symbol: str, interval: str) -> int:
    from app.services.ingestion.candles_ingestion import ingest_latest

    async with session_factory() as session:
        inserted = await ingest_latest(session=session, coin=symbol, interval=interval)
        return int(inserted) if inserted is not None else 0


def _schedule_seconds_for(interval: str) -> int:
    settings = get_settings()
    if settings.INGEST_SCHEDULE_SECONDS and interval in settings.INGEST_SCHEDULE_SECONDS:
        return int(settings.INGEST_SCHEDULE_SECONDS[interval])

    sec = timeframe_seconds(interval)
    return max(15, min(sec // 2, sec))


# ----------------------------
# job loop
# ----------------------------
async def _job_loop(job_id: str, symbol: str, interval: str, stop_event: asyncio.Event, lock: asyncio.Lock) -> None:
    schedule_seconds = _schedule_seconds_for(interval)

    next_tick = time.monotonic()  # run immediately once

    while not stop_event.is_set():
        now = time.monotonic()
        if now < next_tick:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=(next_tick - now))
            except asyncio.TimeoutError:
                pass
            continue

        run_ts = _now_epoch()
        t0 = time.perf_counter()

        try:
            async with lock:
                _state.job_stats[job_id]["last_run_ts"] = run_ts
                logger.info("🕯️ ingest job running | %s", job_id)

                inserted = await _run_ingestion(symbol, interval)

                dt_ms = int((time.perf_counter() - t0) * 1000)
                js = _state.job_stats[job_id]
                js["last_success_ts"] = _now_epoch()
                js["last_success_inserted"] = inserted
                js["last_success_ms"] = dt_ms
                js["consecutive_failures"] = 0

                logger.info("✅ ingest job done | %s | inserted=%s | %dms", job_id, inserted, dt_ms)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            js = _state.job_stats[job_id]
            js["last_error_ts"] = _now_epoch()
            js["last_error"] = (repr(e)[:300])  # bounded for payload sanity
            js["consecutive_failures"] = int(js.get("consecutive_failures", 0)) + 1

            logger.exception("❌ ingest job error | %s | %dms", job_id, dt_ms)

        next_tick += schedule_seconds
        if next_tick < time.monotonic() - schedule_seconds:
            next_tick = time.monotonic() + schedule_seconds


# ----------------------------
# public API
# ----------------------------
def start_scheduler() -> Optional[SchedulerHandle]:
    settings = get_settings()

    if not settings.INGEST_ENABLED:
        logger.info("ℹ️ ingest disabled (INGEST_ENABLED=false)")
        return None

    if _state.started and _state.stop_event and not _state.stop_event.is_set():
        logger.warning("⚠️ scheduler already started (in-process)")
        return SchedulerHandle(_state)

    payload = {
        "pid": os.getpid(),
        "started_at": _now_epoch(),
        "coins": settings.INGEST_COINS,
        "intervals": settings.INGEST_INTERVALS,
    }

    if not _acquire_lock(settings.SCHEDULER_LOCK_PATH, payload):
        lock_pid = _read_lock_pid(settings.SCHEDULER_LOCK_PATH)
        if lock_pid == os.getpid():
            logger.warning("⚠️ scheduler lock exists but matches current PID; proceeding.")
        else:
            logger.warning("⚠️ scheduler lock active (uvicorn --reload duplicate). Not starting a second scheduler.")
            return None

    _state.lock_path = settings.SCHEDULER_LOCK_PATH
    _state.stop_event = asyncio.Event()
    _state.started = True
    _state.meta = payload
    _state.job_stats.clear()

    for coin in settings.INGEST_COINS:
        for interval in settings.INGEST_INTERVALS:
            job_id = f"ingest:{coin}:{interval}"
            if job_id in _state.tasks:
                continue

            lock = asyncio.Lock()
            _state.locks[job_id] = lock

            _state.job_stats[job_id] = {
                "coin": coin,
                "interval": interval,
                "schedule_s": _schedule_seconds_for(interval),
                "last_run_ts": None,
                "last_success_ts": None,
                "last_success_inserted": None,
                "last_success_ms": None,
                "last_error_ts": None,
                "last_error": None,
                "consecutive_failures": 0,
            }

            try:
                task = asyncio.create_task(
                    _job_loop(job_id, coin, interval, _state.stop_event, lock),
                    name=job_id,
                )
            except TypeError:
                task = asyncio.create_task(_job_loop(job_id, coin, interval, _state.stop_event, lock))

            _state.tasks[job_id] = task

    logger.info("✅ candle scheduler started | jobs=%s", len(_state.tasks))
    return SchedulerHandle(_state)


async def stop_scheduler(timeout_s: float = 6.0) -> None:
    if not _state.started:
        return

    stop_event = _state.stop_event
    if stop_event:
        stop_event.set()

    tasks = list(_state.tasks.values())

    try:
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout_s)
    except asyncio.TimeoutError:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        _state.tasks.clear()
        _state.locks.clear()
        _state.started = False
        _state.stop_event = None

        if _state.lock_path:
            _release_lock(_state.lock_path)
            _state.lock_path = None

        _state.meta = {}
        _state.job_stats.clear()

    logger.info("🛑 candle scheduler stopped")
