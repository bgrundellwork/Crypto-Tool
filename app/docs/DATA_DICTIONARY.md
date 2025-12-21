# Data Dictionary

## Candles
- **Primary key**: `(coin, interval, ts)` once Phase 2.5 constraints land.
- **ts**: Unix epoch seconds, UTC normalized, monotonic within `(coin, interval)`.
- **Fields**: `open`, `high`, `low`, `close`, `volume_base`, `volume_quote`, `source`, `ingested_at`.
- **Volume semantics**:
  - `volume_base`: Quantity of the base asset traded within the candle window (e.g., BTC for BTC/USDT markets).
  - `volume_quote`: Notional traded, denominated in the quote asset (e.g., USDT for BTC/USDT).
  - **Flow**: Exchange adapter → ingestion job → DB columns → API serializers → backtest loaders. Backtests should default to `volume_quote` for liquidity filters while allowing overrides to `volume_base` when strategies depend on physical size.
  - **Nullability**: Prior data lacking dual volumes may store `NULL`; ingestion must fill both for new rows. Backtests must defend against null by falling back to whichever column is present.

## Interval Mapping
| Interval | Seconds |
| --- | --- |
| `1m` | 60 |
| `3m` | 180 |
| `5m` | 300 |
| `15m` | 900 |
| `30m` | 1800 |
| `1h` | 3600 |
| `4h` | 14400 |
| `1d` | 86400 |
| `1w` | 604800 |

Ingestion and scheduling modules must use this single mapping to avoid drift. Store mapping in `utils/intervals.py` (source of truth) and import everywhere (scheduler, gap detector, backtests).

## Market Snapshots
- **Primary key**: `(coin, ts)` where ts aligns to actual snapshot event in UTC seconds.
- **Fields**: `price`, `bid`, `ask`, `volume_base`, `volume_quote`, `provider`, `ingested_at`.
- **Usage**: Real-time readiness/health, optional feature inputs.

## Normalization Rules
- **Naming**: snake_case; `coin` lower-case ticker; `interval` stored as lowercase string from mapping table.
- **Timestamps**: Always UTC seconds; provide ISO strings in APIs/backtests using `datetime.utcfromtimestamp`.
- **Precision**: Prices and volumes stored as DOUBLE precision (or Decimal if DB requires) with rounding at 1e-8 for base assets and 1e-4 for quote assets when presenting externally.
- **Nullability**: Avoid nullable numeric fields unless data truly missing; prefer explicit `NULL` + documented fallback rather than sentinel values.
- **Rounding**: Rounding only at serialization layers; DB keeps raw floats from ingestion provider to preserve fidelity.
- **Idempotent ingest**: Upserts keyed by `(coin, interval, ts)` to avoid duplicates.

## Volume Enforcement Checklist
1. Exchange adapters parse both base and quote notional. If upstream offers only one, derive the other using VWAP for the interval and note derivation in logs.
2. DB schema exposes both columns, defaulting to `0` only when exchange reports `0` trades.
3. API schemas return both columns; if null due to legacy data, include `volume_warning=true` in debug payload (optional) while roadmap tasks fix historicals.
4. Backtest loader surfaces `VolumeSemantics` enum so strategies can assert expected column is populated before execution.

## Derived Data
- **Feature Store (Phase 3.5)**: `features` table inherits `coin`, `interval`, `ts` foreign keys referencing candles. Derived columns (ema, atr, etc.) follow same normalization rules. Cache deterministic computations keyed by `(feature_set, coin, interval, ts)`.
- **Risk/Stress Outputs**: When writing stress simulation metrics, capture the exact candle interval + regime metadata to maintain reproducibility.
