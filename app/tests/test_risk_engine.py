from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.risk import RiskConfig
from app.services.risk.engine import label_regimes, run_risk_simulation


def _timestamps(count: int) -> list[datetime]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [base + timedelta(minutes=5 * i) for i in range(count)]


def test_label_regimes_is_deterministic():
    returns = [0.002] * 60 + [-0.003] * 60
    config = RiskConfig(regime_window=20, trend_threshold=0.001, high_vol_threshold=0.002)
    labels_a = label_regimes(returns, config)
    labels_b = label_regimes(returns, config)
    assert labels_a.labels == labels_b.labels
    assert labels_a.summary.top_label in {"bull_trend_low", "bear_trend_low", "bear_trend_high"}


def test_risk_report_monotonic_path():
    returns = [0.001] * 80
    config = RiskConfig(regime_window=10, trend_threshold=0.0005, high_vol_threshold=0.01)
    report = run_risk_simulation(returns, _timestamps(len(returns)), config, seed=42)
    assert report.max_drawdown_pct.p99 == pytest.approx(0.0, abs=1e-9)
    assert report.probability_of_ruin == 0.0
    assert report.regime_summary.labels
    assert report.run_id


def test_risk_report_detects_crash():
    returns = [0.0] * 10 + [-0.5] + [0.0] * 10
    config = RiskConfig(regime_window=5, trend_threshold=0.0001, high_vol_threshold=0.01, ruin_level=0.6)
    report = run_risk_simulation(returns, _timestamps(len(returns)), config, seed=7)
    assert report.max_drawdown_pct.p50 == pytest.approx(50.0, rel=0.01)
    assert report.probability_of_ruin == 1.0
    alpha_key = f"{int(config.var_alpha * 100)}"
    assert alpha_key in report.var_pct
    assert report.var_pct[alpha_key] <= 0.0
