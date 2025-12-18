# app/utils/readiness.py
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Goldman rule: job is stale if age > STALL_MULTIPLIER * schedule_s
STALL_MULTIPLIER_DEFAULT = 2.5


def _to_unix_ts(value: Any) -> Optional[float]:
    """
    Coerce a timestamp-like value into a unix seconds float (UTC).
    Accepts:
      - int/float (assumed unix seconds)
      - datetime (naive assumed UTC)
      - ISO strings (best-effort)
    Returns None if it can't parse.
    """
    if value is None:
        return None

    # unix seconds
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None

    # datetime
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return float(dt.timestamp())

    # string
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None

        # allow "Z"
        s = s.replace("Z", "+00:00")

        # common DB string like "2025-12-17 17:35:00.000000"
        # datetime.fromisoformat can handle "YYYY-MM-DD HH:MM:SS(.ffffff)" too
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return float(dt.timestamp())

    return None


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _make_job_id(job_id: Optional[str], job: Dict[str, Any]) -> str:
    if job_id and str(job_id).strip():
        return str(job_id)
    coin = job.get("coin")
    interval = job.get("interval")
    if coin is not None and interval is not None:
        return f"{coin}:{interval}"
    return "unknown_job"


def annotate_scheduler_jobs(
    scheduler_check: Dict[str, Any],
    now_ts: float | None = None,
    stall_multiplier: float = STALL_MULTIPLIER_DEFAULT,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Enriches your scheduler readiness payload with deterministic, audit-grade stall detection.

    Input (expected shape):
      scheduler_check = {
        "meta": {"started_at": <ts> ...},
        "per_job": { job_id: { "schedule_s": 150, "last_success_ts": <ts>, ...}, ... }
      }

    Output:
      - scheduler_check is updated in-place with per-job:
          age_s, allowed_age_s, stalled, stalled_by_s, never_succeeded,
          ref_ts_unix, ref_ts_key, stall_multiplier
      - returns (scheduler_check, stale_jobs_list)

    Stall rule (Goldman):
      stalled if (now - last_success_ts) > stall_multiplier * schedule_s
      If never succeeded, we use last_run_ts or scheduler started_at as a fallback reference.
    """
    now = float(now_ts) if now_ts is not None else time.time()
    stall_mult = _coerce_float(stall_multiplier, default=STALL_MULTIPLIER_DEFAULT)

    # Normalize per_job into dict[str, dict]
    per_job_raw = scheduler_check.get("per_job") or {}
    per_job: Dict[str, Dict[str, Any]] = {}

    if isinstance(per_job_raw, dict):
        # ensure values are dict-like
        for k, v in per_job_raw.items():
            if isinstance(v, dict):
                per_job[str(k)] = v
            else:
                per_job[str(k)] = {"value": v}
    elif isinstance(per_job_raw, list):
        for item in per_job_raw:
            if not isinstance(item, dict):
                continue
            jid = _make_job_id(item.get("id"), item)
            per_job[jid] = item
    else:
        per_job = {}

    meta = scheduler_check.get("meta") or {}
    started_at_unix = _to_unix_ts(meta.get("started_at"))

    stale: List[Dict[str, Any]] = []

    for raw_job_id, j in per_job.items():
        job_id = _make_job_id(raw_job_id, j)

        schedule_s = _coerce_float(j.get("schedule_s"), default=0.0)
        allowed_age_s = schedule_s * stall_mult if schedule_s > 0 else None

        last_success_unix = _to_unix_ts(j.get("last_success_ts"))
        last_run_unix = _to_unix_ts(j.get("last_run_ts"))

        # Choose reference timestamp used for "age" computation
        # Prefer last_success, else last_run, else scheduler started_at
        ref_ts_unix: Optional[float]
        ref_ts_key: Optional[str]

        if last_success_unix is not None:
            ref_ts_unix, ref_ts_key = last_success_unix, "last_success_ts"
        elif last_run_unix is not None:
            ref_ts_unix, ref_ts_key = last_run_unix, "last_run_ts"
        elif started_at_unix is not None:
            ref_ts_unix, ref_ts_key = started_at_unix, "meta.started_at"
        else:
            ref_ts_unix, ref_ts_key = None, None

        age_s: Optional[float] = None
        if ref_ts_unix is not None:
            age_s = max(0.0, now - float(ref_ts_unix))

        # Determine stalled
        stalled = False
        stalled_by_s = 0.0

        if allowed_age_s is not None and age_s is not None:
            if age_s > allowed_age_s:
                stalled = True
                stalled_by_s = age_s - allowed_age_s

        # Annotate job (in-place)
        j["id"] = j.get("id") or job_id  # preserve existing id if present
        j["stall_multiplier"] = stall_mult
        j["age_s"] = age_s
        j["allowed_age_s"] = allowed_age_s
        j["ref_ts_unix"] = ref_ts_unix
        j["ref_ts_key"] = ref_ts_key
        j["stalled"] = stalled
        j["stalled_by_s"] = stalled_by_s if stalled else 0.0
        j["never_succeeded"] = (last_success_unix is None)

        # Stale summary (for top-level /ready)
        if stalled:
            stale.append(
                {
                    "job_id": job_id,
                    "coin": j.get("coin"),
                    "interval": j.get("interval"),
                    "schedule_s": schedule_s,
                    "age_s": age_s,
                    "allowed_age_s": allowed_age_s,
                    "stalled_by_s": stalled_by_s,
                    "ref_ts_key": ref_ts_key,
                    "last_success_ts": j.get("last_success_ts"),
                    "last_success_iso": j.get("last_success_iso"),
                    "last_error_ts": j.get("last_error_ts"),
                    "last_error_iso": j.get("last_error_iso"),
                    "last_error": j.get("last_error"),
                    "consecutive_failures": j.get("consecutive_failures"),
                    "never_succeeded": (last_success_unix is None),
                }
            )

    # Deterministic ordering (audit-friendly)
    stale.sort(key=lambda x: (-(x.get("stalled_by_s") or 0.0), str(x.get("job_id") or "")))

    # Update scheduler_check (in-place)
    scheduler_check["per_job"] = per_job
    scheduler_check["stale_jobs"] = stale
    scheduler_check["stale_count"] = len(stale)
    scheduler_check["stall_multiplier"] = stall_mult
    scheduler_check["computed_at_ts"] = now

    return scheduler_check, stale
