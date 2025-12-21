# Phase 2.5 Hardening — Engineering Spec (Next)

## 1. Lock `/backtest/run` Contract
- **Problem Statement**: `/backtest/run` currently accepts mixed query params and JSON, creating ambiguous contracts, duplicated OpenAPI schemas, and brittle clients.
- **Implementation Design**:
  - Define `BacktestRunRequest` Pydantic model in `schemas/backtest.py` encapsulating all current inputs.
  - Update `api/backtest.py` route to accept only `request: BacktestRunRequest` body.
  - Add guard: if `request.query_params` contains any of the model fields, raise `HTTPException` 400 with error code `use_json_body`.
  - Ensure OpenAPI schema (FastAPI auto) shows a single requestBody; add description note in router docstring.
- **API Schema**:
```json
POST /backtest/run
Request Body: BacktestRunRequest {
  "coin": "btc",
  "interval": "1h",
  "strategy": "ema_crossover",
  "start_ts": 1700000000,
  "end_ts": 1700500000,
  "params": {"fast": 12, "slow": 26}
}
Response: unchanged success payload or error envelope with code `use_json_body`.
```
- **DB Schema/SQL**: No DB changes.
- **Test Plan**:
  - Unit: `tests/api/test_backtest.py::test_backtest_accepts_json_body`.
  - Negative: `test_backtest_query_params_rejected` verifying 400 payload includes offending keys.
  - OpenAPI snapshot ensures only requestBody defined.
- **Rollout Plan**: Deploy behind feature flag `BACKTEST_JSON_ONLY=false` defaulting to legacy; flip to true after clients ready. Monitor API logs for `use_json_body` errors for 24h, then remove flag.

## 2. Enrich `insufficient_data` Response
- **Problem Statement**: Current error hides actionable context (required candles, latest ts), forcing analysts to guess ingestion windows.
- **Implementation Design**:
  - Introduce `InsufficientDataDetail` model in `schemas/backtest.py` used for both API response and logging.
  - In `services/backtest_runner.py`, when data gap detected compute: `required_candles`, `received_candles`, `required_lookback_seconds`, `latest_candle_ts` (unix + ISO), `suggested_start_ts` (latest `ts` - lookback), `requested_range` object.
  - Response envelope: maintain status (per existing contract) plus `detail` payload and `message`.
- **API Schema**:
```json
{
  "status": "insufficient_data",
  "message": "Need 200 candles; restart from 2023-10-01T00:00:00Z",
  "detail": {
    "coin": "btc",
    "interval": "1h",
    "required_candles": 200,
    "received_candles": 120,
    "required_lookback_seconds": 720000,
    "latest_candle_ts_unix": 1700000000,
    "latest_candle_ts_iso": "2023-11-14T00:00:00Z",
    "suggested_start_ts_unix": 1699280000,
    "suggested_start_ts_iso": "2023-11-06T00:00:00Z",
    "requested_range": {
      "start_ts_unix": 1699000000,
      "end_ts_unix": 1700500000,
      "interval": "1h"
    }
  }
}
```
- **DB Schema/SQL**: None.
- **Test Plan**:
  - Unit: `test_insufficient_data_payload_shape` verifying fields.
  - Unit: `test_suggested_start_ts` verifying correct subtraction even when `latest` null.
  - API integration: simulate missing candles and assert HTTP status + payload.
- **Rollout Plan**: Deploy with feature flag gating new payload; update client SDK; after verifying logs show new response consumed, deprecate old format.

## 3. DB Indexes & Constraints
- **Problem Statement**: Lack of enforced uniqueness and indexes risks duplicate candles/snapshots and slow latest queries.
- **Implementation Design**:
  - Create Alembic migration (preferred) `versions/2024XXXX_add_candle_constraints.py` adding:
    - `ALTER TABLE candles ADD CONSTRAINT uq_candles_coin_interval_ts UNIQUE (coin, interval, ts);`
    - `CREATE INDEX ix_candles_coin_interval_ts_desc ON candles (coin, interval, ts DESC);`
    - `CREATE UNIQUE INDEX uq_market_snapshots_coin_ts ON market_snapshots (coin, ts);`
  - For SQLite dev fallback, run idempotent DDL on startup in `db/migrations.py` if Alembic absent.
  - Update ORM models in `models/candle.py` / `models/market_snapshot.py` with `UniqueConstraint` definitions.
- **API Schema**: Not applicable.
- **DB Schema/SQL**:
```sql
ALTER TABLE candles
  ADD CONSTRAINT uq_candles_coin_interval_ts UNIQUE (coin, interval, ts);
CREATE INDEX IF NOT EXISTS ix_candles_coin_interval_ts_desc
  ON candles (coin, interval, ts DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_snapshots_coin_ts
  ON market_snapshots (coin, ts);
```
- **Test Plan**:
  - DB unit: attempt duplicate candle insert, assert IntegrityError.
  - Query test: ensure latest candle query uses ORDER BY ts DESC LIMIT 1 (explain plan for Postgres in CI optional).
  - Snapshot duplicate test similar.
- **Rollout Plan**: Run migration in staging, verify no duplicates; if duplicates exist, dedupe before applying constraint. Deploy with zero-downtime by adding unique indexes concurrently (Postgres `CREATE UNIQUE INDEX CONCURRENTLY`).

## 4. Snapshot Collector Shutdown Discipline
- **Problem Statement**: Collector risks double-running under reload and may not release resources on shutdown.
- **Implementation Design**:
  - Create `app_locks` table with columns `(name TEXT PRIMARY KEY, owner_id TEXT, acquired_at TIMESTAMP, heartbeat_at TIMESTAMP)`; provide helper in `db/locks.py`.
  - Collector (likely `jobs/snapshot_collector.py`) obtains lock `snapshot_collector` before scheduling tasks; uses UUID owner_id.
  - Add heartbeat coroutine updating `heartbeat_at` every N seconds; stale threshold configurable.
  - FastAPI lifespan (`main.py`) registers shutdown callback to cancel collector tasks and release lock.
- **API Schema**: None.
- **DB Schema/SQL**:
```sql
CREATE TABLE IF NOT EXISTS app_locks (
  name TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  acquired_at TIMESTAMP NOT NULL,
  heartbeat_at TIMESTAMP NOT NULL
);
```
- **Test Plan**:
  - Unit: `test_collector_single_instance` simulating two processes where second fails to acquire lock.
  - Unit: `test_lock_stale_recovery` ensures stale heartbeat allows takeover.
  - Integration: start app, trigger shutdown, verify lock removed.
- **Rollout Plan**: Deploy lock table migration; monitor logs for `collector skipped (already running)` events on reload; add alert for missing heartbeat for >2 intervals.

## 5. Backfill + Gap Detection Workflow
- **Problem Statement**: No automated detection/filling of missing candles causing unreliable backtests.
- **Implementation Design**:
  - Implement `utils/intervals.py` for seconds mapping; used by new `services/gap_detector.py` to compute expected series.
  - Gap detector: query candles for `(coin, interval, start_ts, end_ts)` and produce list of missing ranges.
  - Backfill runner in `scripts/backfill_gaps.py` or `jobs/backfill.py` iterates over missing windows, calling existing ingestion providers (e.g., `services/exchange_client.py`) to fetch needed candles and insert with idempotent upsert.
  - Provide CLI: `python -m scripts.backfill_gaps --coin btc --interval 5m --hours 24` returning JSON summary.
- **API Schema**: Optional admin endpoint if ENV `ENABLE_ADMIN_BACKFILL=true`:
```json
POST /admin/backfill {
  "coin": "btc",
  "interval": "5m",
  "start_ts": 1699500000,
  "end_ts": 1699600000
}
→
{
  "gaps_found": 3,
  "gaps_fixed": 3,
  "candles_added": 150,
  "failed_gaps": []
}
```
- **DB Schema/SQL**: None (uses existing tables).
- **Test Plan**:
  - Unit: `test_gap_detector_identifies_missing_ranges` using synthetic series.
  - Unit: `test_gap_report_counts` for aggregator.
  - Integration: run CLI with fixture DB missing candles and assert candles inserted.
- **Rollout Plan**: Ship CLI first (no endpoint). Run against prod DB with `--dry-run` to confirm detection, then allow writes. After verifying success, optionally expose admin endpoint for ops.

## 6. Volume Definition & Enforcement
- **Problem Statement**: Ambiguous volume semantics between DB, API, and backtests leads to misaligned liquidity assumptions.
- **Implementation Design**:
  - Update `models/candle.py` to include `volume_base` and `volume_quote` (FLOAT). Migrate existing `volume` column by renaming to `volume_base` if already base units; compute quote via `avg_price * volume_base` when available.
  - Update ingestion pipeline to parse both values; if exchange supplies only one, derive the other and mark `derived_volume_quote=true` in logs.
  - Modify API serializers (`schemas/candle.py`) to emit both fields; include `volume_semantics` metadata if necessary.
  - Backtest loader uses `volume_quote` for liquidity filters; add config flag to choose base.
- **API Schema**:
```json
{
  "coin": "btc",
  "interval": "1m",
  "ts": 1700000000,
  "open": 36000.1,
  "high": 36010.2,
  "low": 35980.0,
  "close": 36005.5,
  "volume_base": 15.2,
  "volume_quote": 547,308.6
}
```
- **DB Schema/SQL**:
```sql
ALTER TABLE candles ADD COLUMN volume_base DOUBLE PRECISION;
ALTER TABLE candles ADD COLUMN volume_quote DOUBLE PRECISION;
UPDATE candles SET volume_base = volume WHERE volume_base IS NULL;
UPDATE candles SET volume_quote = ( (open + high + low + close)/4 ) * volume_base
  WHERE volume_quote IS NULL AND volume_base IS NOT NULL;
ALTER TABLE candles DROP COLUMN volume; -- optional after migration
```
- **Test Plan**:
  - Migration test ensures columns exist and data migrated.
  - API serialization test ensures both values returned.
  - Backtest unit ensures loader selects correct volume column per config.
- **Rollout Plan**: Run migration in maintenance window; backfill quote volumes offline before dropping legacy column. Update docs (Data Dictionary). Monitor ingestion logs to ensure both columns populated; add alert if either null for new rows.

## Open Decisions
1. **Backfill interface**: CLI vs admin endpoint. Recommendation: CLI first for safety.
2. **Volume legacy data**: Option A convert existing column to base and derive quote; Option B keep old column read-only. Recommendation: Option A with rolling backfill.
