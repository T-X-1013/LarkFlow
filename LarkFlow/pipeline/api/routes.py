"""RESTful API（§八 冻结契约，D1 空实现）。

端点全量：
  POST /pipelines
  POST /pipelines/{id}/start
  POST /pipelines/{id}/pause | resume | stop
  GET  /pipelines/{id}
  GET  /pipelines/{id}/stages/{stage}/artifact
  POST /pipelines/{id}/checkpoints/{cp}/approve
  POST /pipelines/{id}/checkpoints/{cp}/reject     body: {reason}
  PUT  /pipelines/{id}/provider
  GET  /metrics/pipelines
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pipeline.contracts import (
    Ack,
    ArtifactResponse,
    CheckpointName,
    CheckpointRejectRequest,
    CreatePipelineRequest,
    MetricsItem,
    MetricsResponse,
    PipelineCreateResponse,
    PipelineState,
    ProviderUpdateRequest,
    Stage,
)
from pipeline.api.deps import get_engine, require_checkpoint, require_stage


def create_app() -> FastAPI:
    app = FastAPI(
        title="LarkFlow Pipeline API",
        version="0.1.0",
        description="Pipeline 控制面 RESTful API（§八 契约，D1 冻结）",
    )
    # 前端 MSW mock 与本地联调留白
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========== Pipeline CRUD ==========
    @app.post("/pipelines", response_model=PipelineCreateResponse)
    def create_pipeline(body: CreatePipelineRequest, engine=Depends(get_engine)):
        state = engine.create_pipeline(body.requirement, body.template)
        return PipelineCreateResponse(id=state.id)

    @app.post("/pipelines/{pipeline_id}/start", response_model=PipelineState)
    def start(pipeline_id: str, engine=Depends(get_engine)):
        return _guard(lambda: engine.start(pipeline_id))

    @app.post("/pipelines/{pipeline_id}/pause", response_model=PipelineState)
    def pause(pipeline_id: str, engine=Depends(get_engine)):
        return _guard(lambda: engine.pause(pipeline_id))

    @app.post("/pipelines/{pipeline_id}/resume", response_model=PipelineState)
    def resume(pipeline_id: str, engine=Depends(get_engine)):
        return _guard(lambda: engine.resume(pipeline_id))

    @app.post("/pipelines/{pipeline_id}/stop", response_model=PipelineState)
    def stop(pipeline_id: str, engine=Depends(get_engine)):
        return _guard(lambda: engine.stop(pipeline_id))

    @app.get("/pipelines/{pipeline_id}", response_model=PipelineState)
    def get(pipeline_id: str, engine=Depends(get_engine)):
        return _guard(lambda: engine.get_state(pipeline_id))

    # ========== Artifact ==========
    @app.get(
        "/pipelines/{pipeline_id}/stages/{stage}/artifact",
        response_model=ArtifactResponse,
    )
    def get_artifact(
        pipeline_id: str,
        stage: Stage = Depends(require_stage),
        engine=Depends(get_engine),
    ):
        result = _guard(lambda: engine.get_stage_artifact(pipeline_id, stage))
        return ArtifactResponse(
            stage=stage,
            artifact_path=result.artifact_path or "",
        )

    # ========== Checkpoint (HITL) ==========
    @app.post(
        "/pipelines/{pipeline_id}/checkpoints/{cp}/approve",
        response_model=PipelineState,
    )
    def approve(
        pipeline_id: str,
        cp: CheckpointName = Depends(require_checkpoint),
        engine=Depends(get_engine),
    ):
        return _guard(lambda: engine.approve_checkpoint(pipeline_id, cp))

    @app.post(
        "/pipelines/{pipeline_id}/checkpoints/{cp}/reject",
        response_model=PipelineState,
    )
    def reject(
        pipeline_id: str,
        body: CheckpointRejectRequest,
        cp: CheckpointName = Depends(require_checkpoint),
        engine=Depends(get_engine),
    ):
        return _guard(
            lambda: engine.reject_checkpoint(pipeline_id, cp, body.reason)
        )

    # ========== Provider ==========
    @app.put("/pipelines/{pipeline_id}/provider", response_model=PipelineState)
    def set_provider(
        pipeline_id: str,
        body: ProviderUpdateRequest,
        engine=Depends(get_engine),
    ):
        return _guard(lambda: engine.set_provider(pipeline_id, body.provider))

    # ========== Metrics ==========
    @app.get("/metrics/pipelines", response_model=MetricsResponse)
    def metrics(engine=Depends(get_engine)):
        items = [
            MetricsItem(
                pipeline_id=pid,
                status=state.status,
                stages=state.stages,
            )
            for pid, state in engine.list_states().items()
        ]
        return MetricsResponse(pipelines=items)

    # ========== Health ==========
    @app.get("/healthz", response_model=Ack)
    def healthz():
        return Ack(ok=True)

    return app


def _guard(fn):
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
