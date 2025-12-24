from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.backtest_registry import list_runs, get_run, diff_runs


router = APIRouter(prefix="/registry", tags=["registry"])


class BacktestRunSummary(BaseModel):
    id: str
    created_at: datetime
    strategy_name: str
    code_hash: str
    data_hash: str
    summary: dict[str, Any]


class BacktestRunDetail(BacktestRunSummary):
    inputs: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_curve: list[float]
    feature_hash: str | None


class DiffRequest(BaseModel):
    run_a: str = Field(..., description="First run identifier")
    run_b: str = Field(..., description="Second run identifier")


class DiffResponse(BaseModel):
    run_a: str
    run_b: str
    inputs_diff: dict[str, Any]
    summary_diff: dict[str, Any]


def _deserialize_row(row) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[float]]:
    inputs = json.loads(row.inputs_json)
    summary = json.loads(row.summary_json)
    trades = json.loads(row.trades_json)
    equity = json.loads(row.equity_json)
    return inputs, summary, trades, equity


@router.get("/backtests", response_model=list[BacktestRunSummary])
async def list_backtests(
    strategy_name: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    rows = await list_runs(db, strategy_name=strategy_name, limit=min(limit, 100))
    summaries: list[BacktestRunSummary] = []
    for row in rows:
        _, summary, _, _ = _deserialize_row(row)
        summaries.append(
            BacktestRunSummary(
                id=row.id,
                created_at=row.created_at,
                strategy_name=row.strategy_name,
                code_hash=row.code_hash,
                data_hash=row.data_hash,
                summary=summary,
            )
        )
    return summaries


@router.get("/backtests/{run_id}", response_model=BacktestRunDetail)
async def fetch_backtest(run_id: str, db: AsyncSession = Depends(get_db)) -> BacktestRunDetail:
    row = await get_run(db, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    inputs, summary, trades, equity = _deserialize_row(row)
    return BacktestRunDetail(
        id=row.id,
        created_at=row.created_at,
        strategy_name=row.strategy_name,
        code_hash=row.code_hash,
        data_hash=row.data_hash,
        feature_hash=row.feature_hash,
        summary=summary,
        inputs=inputs,
        trades=trades,
        equity_curve=equity,
    )


@router.post("/backtests/diff", response_model=DiffResponse)
async def diff_backtests(payload: DiffRequest, db: AsyncSession = Depends(get_db)) -> DiffResponse:
    diff = await diff_runs(db, payload.run_a, payload.run_b)
    return DiffResponse(**diff)
