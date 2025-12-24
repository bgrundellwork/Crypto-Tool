from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

import numpy as np

from app.schemas.risk import DistributionSummary, RegimeSummary, RiskConfig, RiskReport
from app.utils.determinism import canonical_json, sha256_str


@dataclass
class RegimeLabels:
    labels: list[str]
    summary: RegimeSummary


def _ensure_np(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError("Returns array must be one-dimensional")
    return array


def _ensure_timestamps(timestamps: Sequence[datetime], expected_len: int) -> list[datetime]:
    if len(timestamps) != expected_len:
        raise ValueError("Timestamps length must match returns length")
    normalized = []
    for ts in timestamps:
        if ts.tzinfo is None:
            normalized.append(ts.replace(tzinfo=timezone.utc))
        else:
            normalized.append(ts.astimezone(timezone.utc))
    return normalized


def _rolling_stats(values: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    if window <= 0 or window > len(values):
        raise ValueError("Window must be in (0, len]")
    cumsum = np.cumsum(np.insert(values, 0, 0.0))
    sums = cumsum[window:] - cumsum[:-window]
    mean = sums / window

    sq = np.cumsum(np.insert(values ** 2, 0, 0.0))
    sq_sums = sq[window:] - sq[:-window]
    var = np.maximum(sq_sums / window - mean ** 2, 0.0)
    std = np.sqrt(var)
    return mean, std


def label_regimes(returns: Sequence[float], config: RiskConfig) -> RegimeLabels:
    arr = _ensure_np(returns)
    if len(arr) < config.regime_window:
        raise ValueError("Not enough returns for regime detection")

    mean, std = _rolling_stats(arr, config.regime_window)
    labels: list[str] = []
    for idx in range(len(arr)):
        if idx < config.regime_window - 1:
            labels.append("warmup")
            continue
        momentum = mean[idx - (config.regime_window - 1)]
        vol = std[idx - (config.regime_window - 1)]
        if abs(momentum) >= config.trend_threshold:
            base = "trend"
            direction = "bull" if momentum > 0 else "bear"
        elif abs(momentum) <= config.range_threshold:
            base = "range"
            direction = "neutral"
        else:
            base = "drift"
            direction = "neutral"
        vol_state = "high" if vol >= config.high_vol_threshold else "low"
        labels.append(f"{direction}_{base}_{vol_state}")

    counts: dict[str, int] = {}
    for label in labels[config.regime_window - 1 :]:
        counts[label] = counts.get(label, 0) + 1
    top_label = max(counts.items(), key=lambda kv: kv[1])[0] if counts else None
    return RegimeLabels(labels=labels, summary=RegimeSummary(labels=counts, top_label=top_label))


def _equity_curve(returns: np.ndarray, start_equity: float) -> np.ndarray:
    equity = np.empty_like(returns)
    cumulative = start_equity
    for idx, r in enumerate(returns):
        cumulative *= 1.0 + r
        equity[idx] = cumulative
    return equity


def _max_drawdown(equity: np.ndarray) -> float:
    peak = equity[0]
    drawdown = 0.0
    for value in equity:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0.0
        if dd > drawdown:
            drawdown = dd
    return drawdown * 100.0


def _time_underwater(equity: np.ndarray) -> list[int]:
    peak = equity[0]
    streak = 0
    durations: list[int] = []
    for value in equity:
        if value < peak:
            streak += 1
        else:
            if streak:
                durations.append(streak)
                streak = 0
            peak = value
    if streak:
        durations.append(streak)
    return durations


def _distribution_summary(samples: Iterable[float]) -> DistributionSummary:
    arr = np.asarray(list(samples), dtype=np.float64)
    if arr.size == 0:
        arr = np.array([0.0])
    return DistributionSummary(
        p50=float(np.percentile(arr, 50)),
        p90=float(np.percentile(arr, 90)),
        p95=float(np.percentile(arr, 95)),
        p99=float(np.percentile(arr, 99)),
    )


def _var_es(values: np.ndarray, alpha: float) -> tuple[float, float]:
    if values.size == 0:
        return 0.0, 0.0
    cutoff = np.quantile(values, 1 - alpha)
    losses = values[values <= cutoff]
    es = float(np.mean(losses)) if losses.size else float(cutoff)
    return float(cutoff), es


def _hash_returns(returns: np.ndarray) -> str:
    payload = [round(float(x), 12) for x in returns]
    return sha256_str(canonical_json(payload))


def run_risk_simulation(
    returns: Sequence[float],
    timestamps: Sequence[datetime],
    config: RiskConfig,
    seed: int = 0,
) -> RiskReport:
    del seed  # reserved for future simulation steps
    arr = _ensure_np(returns)
    if arr.size == 0:
        raise ValueError("Returns series cannot be empty")
    _ensure_timestamps(timestamps, len(arr))

    regimes = label_regimes(arr, config)
    equity = _equity_curve(arr, config.start_equity)
    max_dd = _max_drawdown(equity)
    underwater = _time_underwater(equity)

    var_value, es_value = _var_es(arr, config.var_alpha)
    var_map = {f"{int(config.var_alpha * 100)}": var_value}
    es_map = {f"{int(config.es_alpha * 100)}": es_value}

    ruin_prob = 1.0 if equity.min() <= config.ruin_level else 0.0

    returns_hash = _hash_returns(arr)
    config_hash = sha256_str(canonical_json(config.model_dump()))
    run_components = {
        "engine": config.engine_version,
        "returns": returns_hash,
        "regime_hash": sha256_str(canonical_json(regimes.labels)),
        "config": config_hash,
    }
    run_id = sha256_str(canonical_json(run_components))

    return RiskReport(
        engine_version=config.engine_version,
        run_id=run_id,
        num_paths=1,
        returns_hash=returns_hash,
        config_hash=config_hash,
        max_drawdown_pct=_distribution_summary([max_dd]),
        var_pct=var_map,
        es_pct=es_map,
        probability_of_ruin=ruin_prob,
        time_underwater_bars=_distribution_summary(underwater),
        regime_summary=regimes.summary,
    )

