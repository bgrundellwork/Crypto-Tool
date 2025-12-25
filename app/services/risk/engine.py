from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Iterable, Sequence

from app.schemas.risk import DistributionSummary, RegimeSummary, RiskConfig, RiskReport
from app.utils.determinism import canonical_json, sha256_str


@dataclass
class RegimeLabels:
    labels: list[str]
    summary: RegimeSummary


def _ensure_returns(values: Sequence[float]) -> list[float]:
    try:
        arr = [float(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Returns must be numeric") from exc
    return arr


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


def _rolling_stats(values: list[float], window: int) -> tuple[list[float], list[float]]:
    if window <= 0 or window > len(values):
        raise ValueError("Window must be in (0, len]")
    means: list[float] = []
    stds: list[float] = []
    window_sum = sum(values[:window])
    window_sq = sum(v * v for v in values[:window])
    for idx in range(window, len(values) + 1):
        mean = window_sum / window
        variance = max(window_sq / window - mean * mean, 0.0)
        std = sqrt(variance)
        means.append(mean)
        stds.append(std)
        if idx < len(values):
            window_sum += values[idx] - values[idx - window]
            window_sq += values[idx] ** 2 - values[idx - window] ** 2
    return means, stds


def label_regimes(returns: Sequence[float], config: RiskConfig) -> RegimeLabels:
    arr = _ensure_returns(returns)
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


def _equity_curve(returns: Sequence[float], start_equity: float) -> list[float]:
    equity: list[float] = []
    cumulative = start_equity
    for r in returns:
        cumulative *= 1.0 + r
        equity.append(cumulative)
    return equity


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = equity[0]
    drawdown = 0.0
    for value in equity:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0.0
        if dd > drawdown:
            drawdown = dd
    return drawdown * 100.0


def _time_underwater(equity: Sequence[float]) -> list[int]:
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
    arr = list(samples)
    if not arr:
        arr = [0.0]
    arr_sorted = sorted(arr)
    def pct(p: float) -> float:
        if len(arr_sorted) == 1:
            return float(arr_sorted[0])
        rank = (p / 100.0) * (len(arr_sorted) - 1)
        low = int(rank)
        high = min(low + 1, len(arr_sorted) - 1)
        weight = rank - low
        return float(arr_sorted[low] * (1 - weight) + arr_sorted[high] * weight)

    return DistributionSummary(
        p50=pct(50),
        p90=pct(90),
        p95=pct(95),
        p99=pct(99),
    )


def _var_es(values: Sequence[float], alpha: float) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    sorted_vals = sorted(values)
    threshold_index = max(0, int((1 - alpha) * (len(sorted_vals) - 1)))
    cutoff = sorted_vals[threshold_index]
    losses = [v for v in sorted_vals if v <= cutoff]
    es = sum(losses) / len(losses) if losses else cutoff
    return float(cutoff), float(es)


def _hash_returns(returns: Sequence[float]) -> str:
    payload = [round(float(x), 12) for x in returns]
    return sha256_str(canonical_json(payload))


def run_risk_simulation(
    returns: Sequence[float],
    timestamps: Sequence[datetime],
    config: RiskConfig,
    seed: int = 0,
) -> RiskReport:
    del seed  # reserved for future simulation steps
    arr = _ensure_returns(returns)
    if not arr:
        raise ValueError("Returns series cannot be empty")
    _ensure_timestamps(timestamps, len(arr))

    regimes = label_regimes(arr, config)
    equity = _equity_curve(arr, config.start_equity)
    max_dd = _max_drawdown(equity)
    underwater = _time_underwater(equity)

    var_value, es_value = _var_es(arr, config.var_alpha)
    var_map = {f"{int(config.var_alpha * 100)}": var_value}
    es_map = {f"{int(config.es_alpha * 100)}": es_value}

    ruin_prob = 1.0 if min(equity) <= config.ruin_level else 0.0

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
