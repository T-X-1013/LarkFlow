"""FastAPI 依赖注入：engine facade + checkpoint 名称校验。"""
from __future__ import annotations

from fastapi import HTTPException, Path

from pipeline import engine_api
from pipeline.contracts import CheckpointName, Stage


def get_engine():
    return engine_api


def require_checkpoint(cp: str = Path(..., description="checkpoint 名")) -> CheckpointName:
    try:
        return CheckpointName(cp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown checkpoint: {cp}") from exc


def require_stage(stage: str = Path(..., description="stage 名")) -> Stage:
    try:
        return Stage(stage)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown stage: {stage}") from exc
