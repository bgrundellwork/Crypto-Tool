from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeatureRow
from app.services.candle_reader import fetch_candles_from_db
from app.services.ema import calculate_ema
from app.services.atr import calculate_atr
from app.services.vwap import calculate_vwap
from app.services.zscore import calculate_zscore, closes_to_returns
from app.services.regime import classify_regime
from app.services.signal_engine import compute_signal
from app.services.vov import calculate_vov_from_atr, classify_vov
from app.utils.determinism import canonical_json, hash_candles


@dataclass(frozen=True)
class FeatureSpec:
    feature_set: str = "core_v1"
    schema_version: int = 1
    ema_period: int = 50
    atr_period: int = 14
    z_window: int = 32
    vov_window: int = 20


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)



def _calc_feature_values(
    coin: str,
    interval: str,
    candles: list[dict[str, Any]],
    spec: FeatureSpec,
) -> list[dict[str, Any]]:
    closes = [c["close"] for c in candles]
    ema_series = calculate_ema(closes, spec.ema_period)
    atr_series = calculate_atr(candles, spec.atr_period)
    vwap_series = calculate_vwap(candles)
    returns = closes_to_returns(closes)
    z_series = calculate_zscore(returns, spec.z_window)

    start_idx = max(spec.ema_period - 1, spec.atr_period, spec.z_window)
    features: list[dict[str, Any]] = []

    for idx in range(start_idx, len(candles)):
        price = closes[idx]
        ema = ema_series[idx - (spec.ema_period - 1)]
        atr = atr_series[idx - spec.atr_period]
        z_idx = idx - spec.z_window
        z = z_series[z_idx] if 0 <= z_idx < len(z_series) else 0.0
        vwap = vwap_series[idx]["vwap"]
        atr_history = atr_series[: idx - spec.atr_period + 1]
        vov_value = calculate_vov_from_atr(atr_history, window=spec.vov_window)
        vov_state = classify_vov(vov_value, atr) if vov_value is not None else "stable"
        regime = classify_regime(price=price, ema=ema, atr=atr, zscore=z)
        signal = compute_signal(
            coin=coin,
            interval=interval,
            trend=regime["trend"],
            vol=regime["volatility"],
            momentum=regime["momentum"],
            price=price,
            vwap=vwap,
            atr=atr,
            vov_state=vov_state,
        )
        features.append(
            {
                "ts": _ensure_utc(candles[idx]["timestamp"]),
                "values": {
                    "price": price,
                    "ema": ema,
                    "atr": atr,
                    "vwap": vwap,
                    "zscore": z,
                    "trend": regime["trend"],
                    "volatility": regime["volatility"],
                    "momentum": regime["momentum"],
                    "signal": signal["action"],
                    "confidence": signal["confidence"],
                    "vov_state": vov_state,
                },
            }
        )
    return features


async def materialize_features(
    session: AsyncSession,
    *,
    coin: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
    code_hash: str,
    spec: FeatureSpec | None = None,
) -> list[FeatureRow]:
    spec = spec or FeatureSpec()
    start_ts = _ensure_utc(start_ts)
    end_ts = _ensure_utc(end_ts)
    candles = await fetch_candles_from_db(
        session,
        coin=coin,
        interval=interval,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    if len(candles) < max(spec.ema_period, spec.atr_period + 1, spec.z_window + 1):
        raise ValueError("Insufficient candles to compute features.")

    feature_payloads = _calc_feature_values(coin, interval, candles, spec)
    if not feature_payloads:
        return []
    params_json = canonical_json(
        {
            "ema_period": spec.ema_period,
            "atr_period": spec.atr_period,
            "z_window": spec.z_window,
            "vov_window": spec.vov_window,
        }
    )
    data_hash = hash_candles(candles)
    rows: list[FeatureRow] = []
    for payload in feature_payloads:
        values_json = canonical_json(payload["values"])
        rows.append(
            FeatureRow(
                coin=coin,
                interval=interval,
                ts=_ensure_utc(payload["ts"]),
                feature_set=spec.feature_set,
                schema_version=spec.schema_version,
                params_json=params_json,
                values_json=values_json,
                data_hash=data_hash,
                code_hash=code_hash,
            )
        )
    await _upsert_features(session, rows)
    return rows


async def _upsert_features(session: AsyncSession, rows: Iterable[FeatureRow]) -> None:
    for row in rows:
        exists = await session.execute(
            select(FeatureRow.id).where(
                FeatureRow.coin == row.coin,
                FeatureRow.interval == row.interval,
                FeatureRow.ts == row.ts,
                FeatureRow.feature_set == row.feature_set,
                FeatureRow.schema_version == row.schema_version,
                FeatureRow.data_hash == row.data_hash,
                FeatureRow.code_hash == row.code_hash,
            )
        )
        if exists.scalar_one_or_none():
            continue
        session.add(row)
    await session.commit()


async def fetch_latest_feature(
    session: AsyncSession,
    *,
    coin: str,
    interval: str,
    feature_set: str = "core_v1",
) -> FeatureRow | None:
    result = await session.execute(
        select(FeatureRow)
            .where(
                FeatureRow.coin == coin,
                FeatureRow.interval == interval,
                FeatureRow.feature_set == feature_set,
            )
            .order_by(FeatureRow.ts.desc())
            .limit(1)
    )
    return result.scalars().first()
