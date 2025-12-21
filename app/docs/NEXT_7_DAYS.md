# Next 7 Days — Phase 2.5 Hardening

_All tasks derive directly from the six "🟡 Phase 2.5 — Hardening (Next, in order)" items._

## Day 1 — Lock `/backtest/run` Contract
1. **Model-only request body**
   - Steps: add `BacktestRunRequest` Pydantic model; update router to accept `request: BacktestRunRequest` body; remove query parsing.
   - DoD: Endpoint rejects query params, OpenAPI shows single schema.
   - Test: `pytest tests/api/test_backtest.py::test_backtest_body_only`.
2. **Query param rejection handler**
   - Steps: middleware or endpoint guard collecting unexpected query args; return 400 `use_json_body` payload per standard.
   - DoD: Response includes offending keys list; log occurrence.
   - Test: `pytest tests/api/test_backtest.py::test_backtest_query_param_rejected`.
3. **Swagger docs sync**
   - Steps: regenerate schema (FastAPI auto); ensure docstring/descriptions mention JSON-only.
   - DoD: `/docs` shows single requestBody.
   - Test: `scripts/check_openapi.sh` (or `pytest -k openapi_snapshot`).

## Day 2 — Enrich `insufficient_data`
1. **Response payload struct**
   - Steps: extend API response dataclass with required/received candles, timestamps.
   - DoD: Response matches spec; timestamps include ISO + unix.
   - Test: `pytest tests/api/test_backtest.py::test_insufficient_data_payload`.
2. **Suggested start computation**
   - Steps: function to compute `suggested_start_ts` using lookback + latest candle.
   - DoD: Handles null latest candle; documented fallback.
   - Test: `pytest tests/services/test_candles.py::test_suggested_start`.
3. **Human guidance message**
   - Steps: add textual hint referencing suggested start.
   - DoD: Message present and localized.
   - Test: snapshot test verifying string.

## Day 3 — DB Indexes & Constraints
1. **Schema migration/DDL**
   - Steps: add Alembic migration or startup DDL for candles unique + descending index.
   - DoD: Constraints visible via `PRAGMA index_list` (SQLite) or `
\d` (Postgres).
   - Test: `pytest tests/db/test_constraints.py::test_candles_unique`.
2. **Market snapshot indexes**
   - Steps: create `(coin, ts)` unique/index.
   - DoD: Duplicate insert raises `IntegrityError`.
   - Test: `pytest tests/db/test_constraints.py::test_market_snapshot_unique`.
3. **Query alignment**
   - Steps: ensure ORM queries order by `ts DESC` and limit 1 to exploit index.
   - DoD: Query plans show index usage (manual check) + code review.
   - Test: `pytest tests/services/test_candles.py::test_latest_uses_desc`.

## Day 4 — Snapshot Collector Shutdown Discipline
1. **Lock mechanism**
   - Steps: implement `app_locks` table or file lock; integrate in collector startup.
   - DoD: Reload spawns only one collector.
   - Test: `pytest tests/jobs/test_collector_lock.py` or manual `uvicorn --reload` observation.
2. **Graceful shutdown**
   - Steps: lifespan hook cancels collector task, releases lock.
   - DoD: Logs show release; no pending tasks warnings.
   - Test: `pytest tests/jobs/test_collector_shutdown.py`.
3. **Heartbeat monitoring**
   - Steps: periodic update + stale detection.
   - DoD: Stale lock auto-recovered; metrics exposed.
   - Test: `pytest tests/jobs/test_collector_stale_lock.py`.

## Day 5 — Gap Detection Workflow
1. **Gap detector core**
   - Steps: implement per `(coin, interval)` scanner using interval mapping.
   - DoD: Returns list of missing ranges.
   - Test: `pytest tests/services/test_gap_detector.py`.
2. **Backfill runner**
   - Steps: CLI command or admin endpoint invoking ingestion provider to fill gaps.
   - DoD: Reports `gaps_found`, `gaps_fixed`, `candles_added`.
   - Test: `pytest tests/cli/test_backfill.py` (unit) + manual CLI run.
3. **Reporting/logging**
   - Steps: structured logs + optional JSON artifact summarizing per coin.
   - DoD: Operators can diff before/after counts.
   - Test: Inspect CLI output; `pytest tests/services/test_gap_report.py`.

## Day 6 — Volume Decision Implementation
1. **Schema enforcement**
   - Steps: add `volume_base`, `volume_quote` columns if missing; update ORM models.
   - DoD: New ingests populate both; docs updated.
   - Test: `pytest tests/db/test_volume_columns.py`.
2. **API & backtest wiring**
   - Steps: expose both volumes in API responses & backtest loaders; add validation.
   - DoD: Contracts documented; CI green.
   - Test: `pytest tests/api/test_market_volume.py`, `pytest tests/backtest/test_volume_usage.py`.
3. **Historical handling note**
   - Steps: Document normalization/backfill policy in Data Dictionary.
   - DoD: README/docs mention semantics + warnings.
   - Test: `scripts/md_lint.sh docs/DATA_DICTIONARY.md`.

## Day 7 — Buffer / Verification
1. **Regression sweep**
   - Steps: run `make check`; fix regressions.
   - DoD: All tests pass locally.
   - Test: `make check`.
2. **Observability smoke**
   - Steps: verify /health, /ready, collector logs for new fields.
   - DoD: Endpoints surface new counters.
   - Test: `scripts/curl-health.sh`.
3. **Documentation polish**
   - Steps: ensure ROADMAP, data dictionary, specs updated with final state.
   - DoD: PR description references docs; reviewers have zero ambiguity.
   - Test: `git status` clean aside from intentional changes.
