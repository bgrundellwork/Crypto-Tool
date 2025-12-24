# Phase 3.1 — Backfill Workflow Spec

## Problem Statement
- Research outputs cannot be trusted if candles are missing. Gaps lead to fake returns, distorted drawdowns, and unverifiable risk numbers.
- Manual, unbounded backfills risk duplicate inserts, data drift, and unclear audit trails.
- This phase delivers a bounded, idempotent workflow that detects gaps, fills them using the same ingestion path as scheduled jobs, re-verifies integrity, and refuses research if gaps remain.

## CLI Contract
- Module entry: `python -m app.scripts.backfill`
- Required flags:
  - `--coin <symbol>`
  - `--interval <interval>` (must exist in `utils/intervals.py`)
- Range selection (select exactly one):
  - `--days <int>` (backfills `[now - days, now)` in UTC)
  - `--start <ISO8601>` **and** `--end <ISO8601>`
- Examples:
  - `python -m app.scripts.backfill --coin btc --interval 5m --start 2025-01-01T00:00:00Z --end 2025-01-02T00:00:00Z`
  - `python -m app.scripts.backfill --coin btc --interval 5m --days 7`
- Output: single JSON object on stdout containing status + metrics (see below). Exit code 0 only if the range is complete afterward.

## Boundaries / Caps
- Maximum lookback window: **30 days** (`BACKFILL_MAX_DAYS`, default 30). Longer requests are truncated to the last 30 days and flagged via `caps_hit.window_limit=true`.
- Maximum gap segments processed per run: **100** (`BACKFILL_MAX_GAPS`). Additional gaps remain for future runs (`caps_hit.gap_limit=true`).
- Maximum candles inserted per run: **10,000** (`BACKFILL_MAX_CANDLES`). If reached, remaining gaps stay open (`caps_hit.candle_limit=true`).
- Caps are surfaced in the JSON payload as `caps_hit` so operators know why a run stopped.

## Workflow
1. Normalize requested range to UTC and enforce max lookback.
2. Generate a `GapReport` for `(coin, interval, start_ts, end_ts)` using `services/completeness.py`.
3. If no gaps, emit JSON `{completed: true, gaps_fixed: 0, candles_added: 0}` and exit 0.
4. Otherwise iterate through gaps (respecting caps):
   - Call `services.ingestion.candles_ingestion.ingest_range` for the gap window.
   - Upsert into `candles` via existing ON CONFLICT logic; no new ingestion code was added.
   - After each ingest, run `verify_candle_invariants` to ensure Phase 3 constraints still hold.
   - Re-run `generate_gap_report` to confirm the specific gap closed; increment `gaps_fixed` when confirmed.
5. After all allowed gaps are processed, run `verify_candle_invariants` once more, then `ensure_no_gaps` on the original range.
6. If completeness passes, exit 0 with `completed=true`. If not, emit structured `remaining_gaps` (the serialized `GapReport`) and exit non-zero.

## JSON Output Schema
```
{
  "coin": "btc",
  "interval": "5m",
  "start": { "ts_unix": 1735689600, "ts_iso": "2025-01-01T00:00:00Z" },
  "end":   { "ts_unix": 1735776000, "ts_iso": "2025-01-02T00:00:00Z" },
  "gaps_fixed": 3,
  "candles_added": 450,
  "completed": true,
  "remaining_gaps": null,
  "caps_hit": {
    "window_limit": false,
    "gap_limit": false,
    "candle_limit": false
  },
  "error": null
}
```
- On failure `completed=false`, `remaining_gaps` contains the `GapReport.to_dict()` payload, and `error` is populated if invariants failed or another exception occurred.

## Idempotency & Integrity Guarantees
- Inserts occur via `ingest_range` which already upserts on `(source, coin, interval, ts)` per Phase 3 constraints.
- `verify_candle_invariants` runs after each gap and once at the end, ensuring duplicates/non-monotonic rows never slip in.
- Completeness re-check (`ensure_no_gaps`) guarantees the range is gap-free or the JSON response documents remaining gaps.
- No override or “best effort” flags exist; if gaps remain, the script exits non-zero.

## Failure Modes
| Scenario | Behavior |
| --- | --- |
| Upstream ingestion cannot supply candles (returns 0) | Gap remains open, script exits with `completed=false` and `remaining_gaps` populated. |
| Caps reached | `caps_hit` indicates which limit triggered; remaining gaps stay pending for the next run. |
| Invariants fail after ingest | Script stops immediately, surfaces the assertion message in `error`, and exits non-zero. |
| Invalid interval / inputs | CLI exits with error before touching the DB. |

## Validation Steps
1. `PYTHONPATH=. pytest -q app/tests/db -v`
2. `PYTHONPATH=. pytest -q app/tests/test_completeness.py -v`
3. `PYTHONPATH=. pytest -q app/tests/test_api_backtest.py -v`
4. `PYTHONPATH=. pytest -q app/tests/test_backfill_script.py -v`
5. Manual smoke (optional):
   ```
   python -m app.scripts.backfill --coin btc --interval 5m --days 1
   ```
   Inspect JSON output and ensure exit code matches `completed`.

## Decision Needed
- **Upstream fetcher**: All backfill requests use `services.ingestion.candles_ingestion.ingest_range`, which in turn calls `services.candles.get_candles` (existing path). Alternative data vendors (e.g., external API call) were not added to keep ingestion deterministic.
- **Upsert mechanism**: Continue using SQLite `INSERT ... ON CONFLICT` defined in `ingest_range`. Switching to bulk merges or vendor-specific loaders would add drift; recommendation is to keep current upsert behavior for consistency with scheduler ingests.
