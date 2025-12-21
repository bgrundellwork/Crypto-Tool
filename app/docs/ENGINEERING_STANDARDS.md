# Engineering Standards

## API Contracts
- **JSON-first**: Endpoints that accept structured input (e.g., `/backtest/run`) must require a JSON body backed by a single Pydantic model. Query params for body fields return HTTP 400 with error code `use_json_body`.
- **Version stability**: Breaking response changes require either a new path or explicit version query parameter guarded by feature flag.
- **Schema visibility**: OpenAPI must show one canonical schema per input/output; avoid `oneOf` unless multiple transport types are unavoidable.

## Error Envelope
```
{
  "error": {
    "code": "string",        // machine readable (snake_case)
    "message": "string",     // terse actionable
    "details": {...},         // optional structured context
    "request_id": "uuid"     // propagated from middleware
  }
}
```
- Use HTTP status to reflect class of failure (4xx client, 5xx server).
- Provide deterministic codes for contract violations: `use_json_body`, `insufficient_data`, `duplicate_resource`, etc.

## Database Integrity Rules
- Candles: UNIQUE `(coin, interval, ts)`; enforce monotonic `ts` per `(coin, interval)` using check constraints or ingestion guards.
- Market snapshots: UNIQUE `(coin, ts)`; disallow overlapping inserts.
- Foreign keys reference canonical tables (coins, intervals) when practical; otherwise enforce via check constraints + code validation.
- Every migration must be reversible; no destructive DDL without explicit backup instructions.

## Idempotency & Collectors
- Every ingestion job must be safe to rerun for overlapping windows (use upsert or `INSERT ... ON CONFLICT DO NOTHING`).
- Snapshot collector acquires a DB/file lock before running; releases on shutdown and refreshes heartbeat periodically.
- Jobs record `last_success_ts`, `last_error`, `consecutive_failures` for observability.

## Shutdown & Lifespan
- Use FastAPI lifespan context or `@app.on_event("shutdown")` to cancel background tasks gracefully.
- Track asyncio tasks to cancel them with timeout; log completion.
- On reload/start, collectors verify lock ownership before launching to prevent duplicates.

## Testing & CI
- **Unit tests**: `pytest -m unit` for pure functions (strategy math, serializers). Must run in <1s per module.
- **Integration tests**: `pytest -m integration` hits FastAPI app via TestClient and exercises DB.
- **Data invariants**: Add fixtures validating monotonic timestamps, absence of duplicate candles, and schema expectations.
- **CI gate**: `make check` (or `scripts/check.sh`) runs unit, integration, lint/typecheck in sequence. Sample command block:
```
make check
# equivalent to:
pytest -m unit
pytest -m integration
pytest -m "not unit and not integration"  # optional extended suite
ruff check .  # replace with repo linter
mypy .        # if typing enforced
```
- Do not merge unless `make check` passes locally and in CI.

## Documentation
- Update relevant doc (roadmap, data dictionary, runbooks) with every change that impacts contracts, DB schema, or operational workflows.
- Prefer short `docs/` markdown files linked from README.

## Observability
- Structured logs with `extra={"request_id": ..}`.
- Metrics for API latency, ingestion throughput, job failures; expose via /metrics when Phase 4 lands.
- Health/readiness endpoints must validate DB connectivity, latest candle freshness, scheduler heartbeat.
