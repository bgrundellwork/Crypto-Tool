# Roadmap

## Product Timeline (Source of Truth)
# CRYPTO APP Progres

### **BACKEND**

---

## 

Got you — here’s your **timeline To-Do List** with the **Crypto Volatility Stress Simulation** inserted in the right place.

---

# Crypto FastAPI — Project Timeline To-Do List (Goldman-Tier)

## ✅ Completed (Working Now)

### Phase 1 — Market Analytics API ✅

- Market + indicator + signal endpoints working in Swagger.

### Phase 2 — Data Backbone ✅

- market.db persistent
- market_snapshots filling
- candles filling
- scheduler runs multi-coin × multi-interval

### Phase 2.5 — Hardening ✅ (Upgraded)

- /live, /ready, /health real + reliable
- DB check ✅, candles latest ✅, scheduler running ✅
- Per-job stats visible ✅ (last_success_ts, last_error, consecutive_failures)
- Stall detection fields computed ✅ (age_s, allowed_age_s, stalled_by_s)
- Reload safety via lock file ✅

### Phase 3 — Backtesting MVP ✅

- /backtest/run works end-to-end
- Uses DB candles
- Returns metrics + equity + trades + regime stats
- insufficient_data triggers correctly

---

## 🟡 Phase 2.5 — Hardening (Next, in order)

1. **Lock /backtest/run contract**
- JSON body only (Pydantic)
- query params => 400 “use JSON body”
- Swagger shows one schema
1. **Make insufficient_data self-explanatory**
- required/received candles
- suggested start ts (iso/unix)
- latest candle ts (iso/unix)
- required lookback seconds
1. **DB indexes + constraints**
- candles(coin, interval, ts) UNIQUE
- candles(coin, interval, ts DESC) index
- market_snapshots(coin, ts) index/unique
1. **Snapshot collector shutdown discipline**
- stops cleanly
- no duplicates under reload
1. **Backfill + gap detection workflow**
- gap detector per coin/interval
- backfill fills holes
- report gaps_found/gaps_fixed/candles_added
1. **Decide what “volume” means**
- document + enforce across DB/API/backtests

---

## 🟡 Phase 3.5 — Research & Risk Upgrades (Bloomberg-ish)

A) **Feature Store**

- features(coin, interval, ts, ema, atr, z, vwap, regime, signal, …)
- deterministic + cached computation

B) **Market Microstructure Pack**

- funding, OI, liquidations (if available), basis, realized vol, vol-of-vol

C) **Risk Engine**

- drawdown/exposure
- volatility targeting
- historical VaR / expected shortfall
- correlation matrix (multi-coin)

D) **Walk-forward + regime validation**

- rolling splits
- OOS metrics
- regime sample size checks
- decay detection

E) **Backtest Run Registry**

- backtest_runs table: inputs, outputs summary, trades JSON, git hash, created_at
- endpoints: list / fetch / compare

✅ **F) Crypto Volatility Stress Simulation Suite (Monte Carlo + Regimes + Black Swans)** *(ADDED HERE)*

- **Regime + volatility labels**: realized_vol, vol_regime, trend_regime
- **Block-bootstrap Monte Carlo** on *strategy returns* (block resample, regime-weighted)
- **Regime-switching generator** (HMM/Markov; heavy-tail + vol clustering)
- **Black swan + liquidity shock injector** (gap moves, vol spikes, slippage/spread widening, funding squeeze windows)
- **Volatility scaling** to match current regime (r' = r * σ_now/σ_block)
- New endpoint: POST /risk/simulate returning:
    - max_dd percentiles, ES_99, ruin/liquidation_prob, time-underwater, equity bands

---

## 🟡 Phase 4 — Institutional Engineering Layer

1. **Alembic migrations**
2. **Observability**
- structured logs + request id
- metrics counters (jobs ok/fail, candles inserted)
- optional Prometheus endpoint
1. **Testing & CI gates**
- unit tests (math/strategy)
- integration tests (/ready, /backtest/run)
- data invariants (no dupes, monotonic ts)
- lint/format/typecheck

---

If you want, I can also give you a **“next 7 days execution order”** that turns this timeline into daily tasks without you thinking.

---

## Phase Summaries

### ✅ Phase 1 — Market Analytics API
- **Goal**: Deliver baseline market, indicator, and signal endpoints exposed via FastAPI/Swagger for internal consumption.
- **Scope**: CRUD-less read APIs for spot/indicator data, schema validation, Swagger visibility, response shape stability.
- **Out of Scope**: Persistence, long-running jobs, backtesting, or institutional reporting.
- **Dependencies**: FastAPI app scaffolding, market data provider mocks, schema definitions.
- **Acceptance Criteria**: All endpoints documented in Swagger, responding deterministically with live data, automated smoke test hitting each path.
- **Risk & Mitigations**: Risk of inconsistent indicators mitigated by contract tests and shared validator functions.
- **Observability**: HTTP metrics per endpoint, structured logs with request_id, and FastAPI exception reporting.

### ✅ Phase 2 — Data Backbone
- **Goal**: Persist market data reliably with continuous ingestion for candles and snapshots powering downstream analytics.
- **Scope**: market.db persistence, market_snapshots + candles tables filling via scheduler for multi-coin × multi-interval.
- **Out of Scope**: Advanced analytical transformations, data science feature store, or external warehousing.
- **Dependencies**: Scheduler, ingestion jobs, DB schema alignment.
- **Acceptance Criteria**: Scheduler shows healthy stats, DB tables have monotonic timestamps without gaps for configured intervals, smoke ingestion test passes.
- **Risk & Mitigations**: Risk of clock skew mitigated via UTC normalization and startup readiness checks.
- **Observability**: Job metrics (last_success_ts, consecutive_failures) plus DB row counts exposed via /health.

### 🟡 Phase 2.5 — Hardening (Next)
- **Goal**: Upgrade API contracts, data integrity, and lifecycle management so the system is safe for institutional research consumers.
- **Scope**: /backtest/run JSON-only contract, enriched insufficient_data responses, DB indexes/constraints, snapshot collector shutdown discipline, gap detection/backfill workflow, and volume definition enforcement.
- **Out of Scope**: New analytics features beyond contract hardening or new ingestion sources.
- **Dependencies**: Existing FastAPI endpoints, SQLAlchemy models, ingestion jobs, scheduler hooks.
- **Acceptance Criteria**: Six work items delivered with passing tests, documentation updates, and observable telemetry verifying dedupe and gap metrics.
- **Risk & Mitigations**: Risk of migrations blocking startup mitigated via idempotent DDL + staging verification; risk of ambiguous data semantics mitigated with data dictionary + validations.
- **Observability**: Alerts/logs for collector lock acquisition/release, gap detector reports (gaps_found/fixed), /backtest/run contract enforcement metrics.

### 🟡 Phase 3 — Backtesting MVP
- **Goal**: Provide an operational /backtest/run service using historical candles that returns metrics, equity curves, trades, and regime stats.
- **Scope**: API execution pipeline, DB reads, computation of metrics/regimes, insufficient_data signalling.
- **Out of Scope**: Advanced risk simulations, multi-strategy orchestration, persistence of backtest runs (handled later).
- **Dependencies**: Completed Phase 2 data backbone, strategy libraries.
- **Acceptance Criteria**: Deterministic results for known test fixtures, insufficient_data triggered when required candles missing, API contract versioned.
- **Risk & Mitigations**: Risk of stale data mitigated by readiness checks; risk of mispriced trades mitigated by regression suites.
- **Observability**: Backtest duration metrics, request/response logging with payload hashes.

### 🟡 Phase 3.5 — Research & Risk Upgrades (Bloomberg-ish)
- **Goal**: Layer institutional research capabilities (feature store, microstructure pack, risk engine, walk-forward tooling, run registry, volatility stress simulation).
- **Scope**: Feature store tables, additional market metrics, risk analytics, walk-forward validation, run registry API, POST /risk/simulate Monte Carlo engine per spec.
- **Out of Scope**: Production trade execution or portfolio management automation.
- **Dependencies**: Stable backtesting outputs, enriched market data, compute budget for simulations.
- **Acceptance Criteria**: Each sub-component exposes deterministic APIs/jobs with documentation; /risk/simulate returns required metrics; run registry persists inputs/outputs with git hash.
- **Risk & Mitigations**: Computational cost mitigated via cached computations and configurable windowing; data freshness risk mitigated via pipeline SLAs.
- **Observability**: Feature recompute metrics, risk job latency histograms, registry write audit logs.

### 🔵 Phase 4 — Institutional Engineering Layer
- **Goal**: Add production-grade operational tooling (migrations, observability, CI gates) for institutional deployment confidence.
- **Scope**: Alembic migrations, structured logging + metrics, Prometheus support, comprehensive testing/CI gates including data invariants.
- **Out of Scope**: Product feature work; focus is platform hardening.
- **Dependencies**: Prior phases stable, decision on observability stack, CI environment setup.
- **Acceptance Criteria**: Alembic manages schema, make check (or equivalent) gates unit/integration/lint flows, observability endpoints available.
- **Risk & Mitigations**: Migration drift mitigated by versioned Alembic scripts; CI flakiness mitigated via hermetic fixtures.
- **Observability**: CI dashboards, Prometheus metrics (jobs_ok_total, candles_inserted_total), structured logs with correlation IDs.

## Decision Needed
- **Backfill interface exposure**: Choose between CLI-only workflow (safer for infra) vs admin API (faster operational access). Recommend CLI first to avoid exposing admin endpoints without auth.
- **Volume semantic storage**: Decide if historical candles should be backfilled with both volume_base and volume_quote or retain single column + derived view. Recommendation: dual-column schema with progressive backfill.
