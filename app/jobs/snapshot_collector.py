# app/jobs/snapshot_collector.py
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select

from app.config.settings import get_settings
from app.db.session import session_factory

# your existing provider + storage
from app.services.coingecko import fetch_raw_market_data
from app.services.market_storage import store_market_snapshots

# your existing model name should be MarketSnapshot
from app.db.models import MarketSnapshot


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
        # stale lock cleanup
        try:
            with open(lock_path, "r") as f:
                data = json.load(f)
            pid = int(data.get("pid", -1))
            if _pid_alive(pid):
                return False
        except Exception:
            pass
        try:
            os.remove(lock_path)
        except Exception:
            return False
        return _acquire_lock(lock_path, payload)


def _release_lock(lock_path: str) -> None:
    try:
        os.remove(lock_path)
    except Exception:
        pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SnapshotState:
    started: bool = False
    stop_event: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None
    lock_path: Optional[str] = None
    last_success_utc: Optional[datetime] = None


_state = SnapshotState()


async def _latest_snapshot_ts(coin_id: str) -> Optional[datetime]:
    async with session_factory() as session:
        q = select(func.max(MarketSnapshot.timestamp)).where(MarketSnapshot.coin_id == coin_id)
        res = await session.execute(q)
        ts = res.scalar_one_or_none()
        if ts is None:
            return None
        # make tz-aware UTC
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)


async def _warn_if_stale(coins: list[str], stale_minutes: int) -> None:
    # only checks one coin if you want to keep it minimal, but this checks all in list
    now = _utc_now()
    for c in coins:
        latest = await _latest_snapshot_ts(c)
        if latest is None:
            print(f"⚠️ snapshot stale | coin={c} | no snapshots in DB yet")
            continue
        age_min = (now - latest).total_seconds() / 60.0
        if age_min > stale_minutes:
            print(f"⚠️ snapshot stale | coin={c} | last={latest.isoformat()} | age_min={age_min:.1f}")


async def _fetch_with_retries() -> list[dict]:
    s = get_settings()
    attempt = 0
    while True:
        try:
            return await fetch_raw_market_data()
        except Exception as e:
            attempt += 1
            if attempt > s.SNAPSHOT_MAX_RETRIES:
                raise
            backoff = (s.SNAPSHOT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))) + random.uniform(
                0.0, s.SNAPSHOT_JITTER_SECONDS
            )
            print(f"⚠️ snapshot fetch failed | attempt={attempt}/{s.SNAPSHOT_MAX_RETRIES} | err={e} | sleep={backoff:.2f}s")
            await asyncio.sleep(backoff)


async def _snapshot_loop(stop_event: asyncio.Event) -> None:
    s = get_settings()
    interval = max(5, int(s.SNAPSHOT_INTERVAL_SECONDS))

    print(f"✅ snapshot collector started | interval_s={interval}")

    while not stop_event.is_set():
        t0 = time.time()
        try:
            data = await _fetch_with_retries()
            await store_market_snapshots(data)
            _state.last_success_utc = _utc_now()
            dt_ms = int((time.time() - t0) * 1000)
            print(f"✅ snapshots stored | ms={dt_ms}")
        except Exception as e:
            dt_ms = int((time.time() - t0) * 1000)
            print(f"❌ snapshots error | ms={dt_ms} | err={e}")

        # coverage monitoring (warn if stale)
        try:
            await _warn_if_stale(s.INGEST_COINS, s.SNAPSHOT_STALE_THRESHOLD_MINUTES)
        except Exception as e:
            print(f"⚠️ snapshot monitor error | err={e}")

        # stop-aware sleep
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    print("🛑 snapshot collector stopped")


def start_snapshot_collector() -> None:
    s = get_settings()
    if not s.SNAPSHOT_ENABLED:
        print("ℹ️ snapshot disabled (SNAPSHOT_ENABLED=false)")
        return

    if _state.started:
        print("⚠️ snapshot collector already started (in-process)")
        return

    payload = {"pid": os.getpid(), "started_at": time.time()}
    if not _acquire_lock(s.SNAPSHOT_LOCK_PATH, payload):
        print("⚠️ snapshot lock active (likely uvicorn --reload duplicate). Not starting a second collector.")
        return

    _state.lock_path = s.SNAPSHOT_LOCK_PATH
    _state.stop_event = asyncio.Event()
    _state.started = True

    loop = asyncio.get_event_loop()
    _state.task = loop.create_task(_snapshot_loop(_state.stop_event))


async def stop_snapshot_collector() -> None:
    if not _state.started:
        return

    if _state.stop_event:
        _state.stop_event.set()

    if _state.task:
        _state.task.cancel()
        await asyncio.gather(_state.task, return_exceptions=True)

    _state.task = None
    _state.stop_event = None
    _state.started = False

    if _state.lock_path:
        _release_lock(_state.lock_path)
        _state.lock_path = None
