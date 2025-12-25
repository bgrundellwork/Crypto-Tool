from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, Field


class DistributionSummary(BaseModel):
    """Percentile summary for simulated metrics."""

    p50: float
    p90: float
    p95: float
    p99: float


class RegimeSummary(BaseModel):
    """Count of assigned regime labels."""

    labels: Dict[str, int]
    top_label: Optional[str] = None


class RiskConfig(BaseModel):
    """Configuration for the volatility & risk engine."""

    engine_version: str = "v1-core"
    interval_minutes: int = Field(5, gt=0)
    regime_window: int = Field(48, ge=5)
    trend_threshold: float = Field(0.0005, ge=0)
    range_threshold: float = Field(0.0001, ge=0)
    high_vol_threshold: float = Field(0.01, ge=0)
    var_alpha: float = Field(0.95, gt=0, lt=1)
    es_alpha: float = Field(0.95, gt=0, lt=1)
    ruin_level: float = Field(0.5, gt=0)
    start_equity: float = Field(1.0, gt=0)


class RiskReport(BaseModel):
    """Output metrics for a risk simulation run."""

    engine_version: str
    run_id: str
    num_paths: int
    returns_hash: str
    config_hash: str
    max_drawdown_pct: DistributionSummary
    var_pct: Dict[str, float]
    es_pct: Dict[str, float]
    probability_of_ruin: float
    time_underwater_bars: DistributionSummary
    regime_summary: RegimeSummary

