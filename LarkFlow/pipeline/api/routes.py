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
    MetricsResponse,
    PipelineCreateResponse,
    PipelineState,
    ProviderUpdateRequest,
    Stage,
)
from pipeline.api.deps import get_engine, require_checkpoint, require_stage


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用并注册全部 Pipeline 控制端点。

    @params:
        无

    @return:
        返回配置完成的 FastAPI 应用实例
    """
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
        """
        创建一条新的 Pipeline 控制记录。

        @params:
            body: 创建请求，包含需求文本和可选模板名
            engine: 由依赖注入提供的 engine facade

        @return:
            返回仅包含 pipeline id 的创建结果
        """
        state = engine.create_pipeline(body.requirement, body.template)
        return PipelineCreateResponse(id=state.id)

    @app.post("/pipelines/{pipeline_id}/start", response_model=PipelineState)
    def start(pipeline_id: str, engine=Depends(get_engine)):
        """
        启动指定 Pipeline。

        @params:
            pipeline_id: 目标 Pipeline ID
            engine: 由依赖注入提供的 engine facade

        @return:
            返回启动后的最新 PipelineState
        """
        return _guard(lambda: engine.start(pipeline_id))

    @app.post("/pipelines/{pipeline_id}/pause", response_model=PipelineState)
    def pause(pipeline_id: str, engine=Depends(get_engine)):
        """
        暂停指定 Pipeline。

        @params:
            pipeline_id: 目标 Pipeline ID
            engine: 由依赖注入提供的 engine facade

        @return:
            返回暂停后的最新 PipelineState
        """
        return _guard(lambda: engine.pause(pipeline_id))

    @app.post("/pipelines/{pipeline_id}/resume", response_model=PipelineState)
    def resume(pipeline_id: str, engine=Depends(get_engine)):
        """
        恢复指定 Pipeline。

        @params:
            pipeline_id: 目标 Pipeline ID
            engine: 由依赖注入提供的 engine facade

        @return:
            返回恢复后的最新 PipelineState
        """
        return _guard(lambda: engine.resume(pipeline_id))

    @app.post("/pipelines/{pipeline_id}/stop", response_model=PipelineState)
    def stop(pipeline_id: str, engine=Depends(get_engine)):
        """
        停止指定 Pipeline。

        @params:
            pipeline_id: 目标 Pipeline ID
            engine: 由依赖注入提供的 engine facade

        @return:
            返回停止后的最新 PipelineState
        """
        return _guard(lambda: engine.stop(pipeline_id))

    @app.get("/pipelines", response_model=list[PipelineState])
    def list_pipelines(engine=Depends(get_engine)):
        """
        列出所有已注册 Pipeline 的状态快照，供前端列表页消费。

        @params:
            engine: 由依赖注入提供的 engine facade

        @return:
            返回 PipelineState 列表
        """
        return engine.list_pipelines()

    @app.get("/pipelines/{pipeline_id}", response_model=PipelineState)
    def get(pipeline_id: str, engine=Depends(get_engine)):
        """
        查询指定 Pipeline 的当前状态快照。

        @params:
            pipeline_id: 目标 Pipeline ID
            engine: 由依赖注入提供的 engine facade

        @return:
            返回当前 PipelineState
        """
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
        """
        查询指定阶段的产物路径。

        @params:
            pipeline_id: 目标 Pipeline ID
            stage: 已校验的阶段枚举
            engine: 由依赖注入提供的 engine facade

        @return:
            返回阶段产物响应
        """
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
        """
        通过指定 HITL 检查点。

        @params:
            pipeline_id: 目标 Pipeline ID
            cp: 已校验的检查点名称
            engine: 由依赖注入提供的 engine facade

        @return:
            返回审批后的最新 PipelineState
        """
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
        """
        驳回指定 HITL 检查点。

        @params:
            pipeline_id: 目标 Pipeline ID
            body: 驳回请求，包含原因
            cp: 已校验的检查点名称
            engine: 由依赖注入提供的 engine facade

        @return:
            返回驳回后的最新 PipelineState
        """
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
        """
        在启动前更新指定 Pipeline 的大模型 Provider。

        @params:
            pipeline_id: 目标 Pipeline ID
            body: Provider 更新请求
            engine: 由依赖注入提供的 engine facade

        @return:
            返回更新后的最新 PipelineState
        """
        return _guard(lambda: engine.set_provider(pipeline_id, body.provider))

    # ========== Metrics ==========
    @app.get("/metrics/pipelines", response_model=MetricsResponse)
    def metrics(engine=Depends(get_engine)):
        """
        汇总全部 Pipeline 的指标快照。

        @params:
            engine: 由依赖注入提供的 engine facade

        @return:
            返回 MetricsResponse
        """
        return MetricsResponse(pipelines=engine.list_metrics())

    # ========== Health ==========
    @app.get("/healthz", response_model=Ack)
    def healthz():
        """
        返回服务健康检查结果。

        @params:
            无

        @return:
            返回固定的 `ok=True` 响应
        """
        return Ack(ok=True)

    return app


def _guard(fn):
    """
    把 engine facade 抛出的常见异常映射为 HTTP 状态码。

    @params:
        fn: 需要执行的业务函数

    @return:
        返回业务函数原始返回值；出错时抛出对应 HTTPException
    """
    try:
        return fn()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
