# app/jobs/scheduler.py
from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.config.settings import get_settings
from app.db.session import session_factory

# ---- timeframe -> seconds mapping ----
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
    # Try to use your existing mapping if present
    try:
        from app.config.timeframes import TIMEFRAME_SECONDS  # type: ignore
        return int(TIMEFRAME_SECONDS[tf])
    except Exception:
        pass

    try:
        from app.config.timeframes import TIMEFRAMES  # type: ignore
        # If TIMEFRAMES is like {"15m":900,...}
        if isinstance(TIMEFRAMES, dict) and tf in TIMEFRAMES:
            return int(TIMEFRAMES[tf])
    except Exception:
        pass

    mapping = _default_timeframe_seconds()
    if tf not in mapping:
        raise ValueError(f"Unknown interval/timeframe: {tf}")
    return mapping[tf]


# ---- lock file (prevent duplicate scheduler under --reload) ----
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _acquire_lock(lock_path: str, payload: dict) -> bool:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        return True
    except FileExistsError:
        # If lock exists, see if it's stale
        try:
            with open(lock_path, "r") as f:
                data = json.load(f)
            pid = int(data.get("pid", -1))
            if _pid_alive(pid):
                return False  # active scheduler
        except Exception:
            pass
        # stale lock -> remove and retry once
        try:
            os.remove(lock_path)
        except Exception:
            return False
        return _acquire_lock(lock_path, payload)


def _release_lock(lock_path: str) -> None:
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        return
    except Exception:
        return


@dataclass
class SchedulerState:
    started: bool = False
    stop_event: Optional[asyncio.Event] = None
    tasks: Dict[str, asyncio.Task] = None  # job_id -> task
    per_job_lock: Dict[str, asyncio.Lock] = None
    lock_path: Optional[str] = None


_state = SchedulerState(tasks={}, per_job_lock={})


# ---- IMPORTANT: adapt this import/call to your ingestion function ----
async def _run_ingestion(symbol: str, interval: str) -> int:
    """
    Returns candles_inserted (int).
    Uses your real ingestion entrypoint: ingest_latest(session, coin, interval)
    """
    from app.services.ingestion.candles_ingestion import ingest_latest

    async with session_factory() as session:
        inserted = await ingest_latest(session=session, coin=symbol, interval=interval)
        return int(inserted) if inserted is not None else 0



def _schedule_seconds_for(interval: str) -> int:
    settings = get_settings()
    if settings.INGEST_SCHEDULE_SECONDS and interval in settings.INGEST_SCHEDULE_SECONDS:
        return int(settings.INGEST_SCHEDULE_SECONDS[interval])

    # default: run at ~1/2 of bar size (frequent enough to catch new data),
    # but clamp to a sensible minimum to avoid hammering
    sec = timeframe_seconds(interval)
    return max(15, min(sec // 2, sec))


async def _job_loop(job_id: str, symbol: str, interval: str, stop_event: asyncio.Event) -> None:
    lock = _state.per_job_lock[job_id]
    schedule_seconds = _schedule_seconds_for(interval)

    while not stop_event.is_set():
        t0 = time.time()
        async with lock:
            print(f"🕯️ ingest job running | {job_id}")
            try:
                inserted = await _run_ingestion(symbol, interval)
                dt_ms = int((time.time() - t0) * 1000)
                print(f"✅ ingest job done | {job_id} | inserted={inserted} | {dt_ms}ms")
            except Exception as e:
                dt_ms = int((time.time() - t0) * 1000)
                print(f"❌ ingest job error | {job_id} | {dt_ms}ms | err={e}")

        # sleep (stop-aware)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=schedule_seconds)
        except asyncio.TimeoutError:
            pass


def start_scheduler() -> None:
    settings = get_settings()
    if not settings.INGEST_ENABLED:
        print("ℹ️ ingest disabled (INGEST_ENABLED=false)")
        return

    if _state.started:
        print("⚠️ scheduler already started (in-process)")
        return

    payload = {
        "pid": os.getpid(),
        "started_at": time.time(),
        "coins": settings.INGEST_COINS,
        "intervals": settings.INGEST_INTERVALS,
    }

    if not _acquire_lock(settings.SCHEDULER_LOCK_PATH, payload):
        print("⚠️ scheduler lock active (likely uvicorn --reload duplicate). Not starting a second scheduler.")
        return

    _state.lock_path = settings.SCHEDULER_LOCK_PATH
    _state.stop_event = asyncio.Event()
    _state.started = True

    loop = asyncio.get_event_loop()

    # create tasks
    for coin in settings.INGEST_COINS:
        for interval in settings.INGEST_INTERVALS:
            job_id = f"ingest:{coin}:{interval}"
            if job_id in _state.tasks:
                continue
            _state.per_job_lock[job_id] = asyncio.Lock()
            task = loop.create_task(_job_loop(job_id, coin, interval, _state.stop_event))
            _state.tasks[job_id] = task

    print(f"✅ candle scheduler started | jobs={len(_state.tasks)}")


async def stop_scheduler() -> None:
    if not _state.started:
        return

    if _state.stop_event:
        _state.stop_event.set()

    # cancel tasks politely
    for job_id, task in list(_state.tasks.items()):
        task.cancel()

    await asyncio.gather(*_state.tasks.values(), return_exceptions=True)
    _state.tasks.clear()
    _state.per_job_lock.clear()

    _state.started = False

    if _state.lock_path:
        _release_lock(_state.lock_path)
        _state.lock_path = None

    print("🛑 candle scheduler stopped")
