from __future__ import annotations

from datetime import datetime
from typing import Any, List
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.feature_store import FeatureSpec, materialize_features, fetch_latest_feature

router = APIRouter(prefix="/features", tags=["features"])


class FeatureParams(BaseModel):
    ema_period: int = Field(50, ge=2)
    atr_period: int = Field(14, ge=2)
    z_window: int = Field(32, ge=2)
    vov_window: int = Field(20, ge=2)


class MaterializeRequest(BaseModel):
    coin: str
    interval: str
    start_ts: datetime
    end_ts: datetime
    feature_set: str = "core_v1"
    schema_version: int = 1
    params: FeatureParams = FeatureParams()
    code_hash: str = Field(..., min_length=1)


class FeatureRecord(BaseModel):
    ts: datetime
    values: dict[str, Any]


class MaterializeResponse(BaseModel):
    coin: str
    interval: str
    feature_set: str
    schema_version: int
    params_json: str
    data_hash: str
    code_hash: str
    features: List[FeatureRecord]


@router.post("/materialize", response_model=MaterializeResponse)
async def materialize_endpoint(payload: MaterializeRequest, db: AsyncSession = Depends(get_db)) -> MaterializeResponse:
    if payload.end_ts <= payload.start_ts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_ts must be after start_ts.")
    spec = FeatureSpec(
        feature_set=payload.feature_set,
        schema_version=payload.schema_version,
        ema_period=payload.params.ema_period,
        atr_period=payload.params.atr_period,
        z_window=payload.params.z_window,
        vov_window=payload.params.vov_window,
    )
    try:
        rows = await materialize_features(
            db,
            coin=payload.coin,
            interval=payload.interval,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            code_hash=payload.code_hash,
            spec=spec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No feature rows produced.")

    features = [
        FeatureRecord(ts=row.ts, values=json.loads(row.values_json))
        for row in rows
    ]

    return MaterializeResponse(
        coin=payload.coin,
        interval=payload.interval,
        feature_set=spec.feature_set,
        schema_version=spec.schema_version,
        params_json=rows[0].params_json,
        data_hash=rows[0].data_hash,
        code_hash=rows[0].code_hash,
        features=features,
    )


class LatestFeatureResponse(BaseModel):
    coin: str
    interval: str
    feature_set: str
    schema_version: int
    ts: datetime
    values: dict[str, Any]


@router.get("/latest", response_model=LatestFeatureResponse)
async def latest_feature(
    coin: str,
    interval: str,
    feature_set: str = "core_v1",
    db: AsyncSession = Depends(get_db),
) -> LatestFeatureResponse:
    row = await fetch_latest_feature(
        db,
        coin=coin,
        interval=interval,
        feature_set=feature_set,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No features found.")
    return LatestFeatureResponse(
        coin=row.coin,
        interval=row.interval,
        feature_set=row.feature_set,
        schema_version=row.schema_version,
        ts=row.ts,
        values=json.loads(row.values_json),
    )
