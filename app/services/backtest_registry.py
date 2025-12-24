from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BacktestRun
from app.utils.determinism import canonical_json, sha256_str


@dataclass(frozen=True)
class BacktestRunPayload:
    strategy_name: str
    inputs: dict[str, Any]
    summary: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_curve: list[float]
    code_hash: str
    data_hash: str
    feature_hash: str | None = None


def _canonical(value: Any) -> str:
    return canonical_json(value)


def _compute_run_hash(payload: BacktestRunPayload) -> str:
    components = {
        "strategy": payload.strategy_name,
        "inputs": payload.inputs,
        "summary": payload.summary,
        "trades": payload.trades,
        "equity": payload.equity_curve,
        "code_hash": payload.code_hash,
        "data_hash": payload.data_hash,
        "feature_hash": payload.feature_hash,
    }
    return sha256_str(_canonical(components))


async def save_run(session: AsyncSession, payload: BacktestRunPayload) -> BacktestRun:
    run_hash = _compute_run_hash(payload)
    existing = await session.execute(
        select(BacktestRun).where(BacktestRun.run_hash == run_hash)
    )
    row = existing.scalars().first()
    if row:
        return row

    row = BacktestRun(
        strategy_name=payload.strategy_name,
        inputs_json=_canonical(payload.inputs),
        summary_json=_canonical(payload.summary),
        trades_json=_canonical(payload.trades),
        equity_json=_canonical(payload.equity_curve),
        code_hash=payload.code_hash,
        data_hash=payload.data_hash,
        feature_hash=payload.feature_hash,
        run_hash=run_hash,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_runs(
    session: AsyncSession,
    *,
    strategy_name: str | None = None,
    limit: int = 20,
) -> list[BacktestRun]:
    stmt = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
    if strategy_name:
        stmt = stmt.where(BacktestRun.strategy_name == strategy_name)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_run(session: AsyncSession, run_id: str) -> BacktestRun | None:
    result = await session.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    return result.scalars().first()


def _diff_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    keys = set(left.keys()) | set(right.keys())
    for key in keys:
        lval = left.get(key)
        rval = right.get(key)
        if lval != rval:
            diff[key] = {"left": lval, "right": rval}
    return diff


async def diff_runs(session: AsyncSession, run_a: str, run_b: str) -> dict[str, Any]:
    first = await get_run(session, run_a)
    second = await get_run(session, run_b)
    if not first or not second:
        raise ValueError("Both runs must exist to diff.")

    first_inputs = json.loads(first.inputs_json)
    second_inputs = json.loads(second.inputs_json)
    first_summary = json.loads(first.summary_json)
    second_summary = json.loads(second.summary_json)

    return {
        "run_a": first.id,
        "run_b": second.id,
        "inputs_diff": _diff_dicts(first_inputs, second_inputs),
        "summary_diff": _diff_dicts(first_summary, second_summary),
    }
