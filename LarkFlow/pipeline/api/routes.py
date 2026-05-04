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

from pipeline.core.contracts import (
    Ack,
    ArtifactResponse,
    CheckpointName,
    CheckpointRejectRequest,
    CreatePipelineFromDocRequest,
    CreatePipelineRequest,
    DemandListItem,
    MetricsResponse,
    PipelineStatus,
    PipelineCreateResponse,
    PipelineState,
    ProviderUpdateRequest,
    Stage,
    VisualEditCommitPlan,
    VisualEditCommitRequest,
    VisualEditCommitResult,
    VisualEditDeliveryCheck,
    VisualEditPreviewRequest,
    VisualEditSession,
)
from pipeline.api.deps import get_engine, require_checkpoint, require_stage
from pipeline.lark.bitable_listener import create_bitable_record, list_bitable_records
from pipeline.lark.doc_reader import LarkDocReadError, extract_document_id, read_feishu_doc
from pipeline.ops.visual_edit import (
    VisualEditNotFoundError,
    VisualEditRequestError,
    cancel_preview,
    commit_visual_edit,
    confirm_preview,
    create_preview,
    delivery_check,
    get_session as get_visual_edit_session,
    prepare_commit,
)


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

    def _map_bitable_status(status: str) -> tuple[PipelineStatus, Stage | None]:
        """
        把多维表格中的中文状态映射为前端契约状态。

        @params:
            status: Base 状态列中的原始中文值

        @return:
            返回 `(PipelineStatus, Stage | None)`；无法识别时回退为 pending
        """
        normalized = (status or "").strip()
        if normalized == "设计审批中":
            return PipelineStatus.WAITING_APPROVAL, Stage.DESIGN
        if normalized in {"设计已通过", "编码中"}:
            return PipelineStatus.RUNNING, Stage.CODING
        if normalized == "测试中":
            return PipelineStatus.RUNNING, Stage.TEST
        if normalized == "审查中":
            return PipelineStatus.RUNNING, Stage.REVIEW
        if normalized == "部署审批中":
            return PipelineStatus.WAITING_APPROVAL, Stage.REVIEW
        if normalized == "部署中":
            return PipelineStatus.RUNNING, Stage.REVIEW
        if normalized == "已暂停":
            return PipelineStatus.PAUSED, None
        if normalized == "已停止":
            return PipelineStatus.STOPPED, None
        if normalized == "驳回":
            return PipelineStatus.REJECTED, None
        if normalized in {"失败", "部署失败"}:
            return PipelineStatus.FAILED, None
        if normalized == "已完成":
            return PipelineStatus.SUCCEEDED, None
        return PipelineStatus.PENDING, None

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

    # ========== From Feishu Doc ==========
    @app.post("/pipelines/from-doc", response_model=PipelineCreateResponse)
    def create_pipeline_from_doc(body: CreatePipelineFromDocRequest, engine=Depends(get_engine)):
        """
        从飞书文档创建 Pipeline。

        流程：
        1. 从 URL 提取 document_id
        2. 通过飞书 Drive API 读取文档内容
        3. 在多维表格中创建新记录
        4. 创建 pipeline（内存态，等待 bitable 事件触发真实流程）

        @params:
            body: 请求体，包含飞书文档 URL
            engine: engine facade

        @return:
            返回 pipeline id
        """
        # 1. 从 URL 提取 document_id
        document_id = extract_document_id(body.doc_url)
        if not document_id:
            raise HTTPException(status_code=400, detail="无效的飞书文档链接格式")

        # 2. 读取文档内容
        try:
            doc_data = read_feishu_doc(document_id, body.doc_url)
        except LarkDocReadError as exc:
            raise HTTPException(status_code=400, detail=f"读取文档失败：{exc}") from exc

        # 3. 构建需求描述
        requirement = f"{doc_data['title']}\n\n{doc_data['content']}"

        # 4. 在多维表格中创建记录
        try:
            create_bitable_record(requirement=requirement, doc_url=body.doc_url)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"创建多维表格记录失败：{exc}") from exc

        # 5. 创建 pipeline（内存态）
        state = engine.create_pipeline(requirement, body.template if hasattr(body, 'template') else 'default')
        return PipelineCreateResponse(id=state.id)

    # ========== Visual Edit ==========
    @app.post("/visual-edits/preview", response_model=VisualEditSession)
    def create_visual_edit_preview(body: VisualEditPreviewRequest):
        """
        创建一次视觉编辑预览会话。

        @params:
            body: 预览请求，包含圈选目标、页面信息和修改意图

        @return:
            返回最新视觉编辑会话
        """
        try:
            return create_preview(body)
        except VisualEditRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/visual-edits/{session_id}", response_model=VisualEditSession)
    def get_visual_edit(session_id: str):
        """
        查询指定视觉编辑会话。

        @params:
            session_id: 视觉编辑会话 ID

        @return:
            返回会话快照
        """
        try:
            return get_visual_edit_session(session_id)
        except VisualEditNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"visual edit session not found: {session_id}") from exc

    @app.post("/visual-edits/{session_id}/confirm", response_model=VisualEditSession)
    def confirm_visual_edit(session_id: str):
        """
        确认预览结果并保留本次修改。

        @params:
            session_id: 视觉编辑会话 ID

        @return:
            返回确认后的会话快照
        """
        try:
            return confirm_preview(session_id)
        except VisualEditNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"visual edit session not found: {session_id}") from exc
        except VisualEditRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/visual-edits/{session_id}/cancel", response_model=VisualEditSession)
    def cancel_visual_edit(session_id: str):
        """
        取消预览并回滚临时改动。

        @params:
            session_id: 视觉编辑会话 ID

        @return:
            返回取消后的会话快照
        """
        try:
            return cancel_preview(session_id)
        except VisualEditNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"visual edit session not found: {session_id}") from exc
        except VisualEditRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/visual-edits/{session_id}/delivery-check", response_model=VisualEditDeliveryCheck)
    def check_visual_edit_delivery(session_id: str):
        """
        检查当前视觉编辑文件是否适合直接提交。

        @params:
            session_id: 视觉编辑会话 ID

        @return:
            返回交付检查结果
        """
        try:
            return delivery_check(session_id)
        except VisualEditNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"visual edit session not found: {session_id}") from exc
        except VisualEditRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/visual-edits/{session_id}/prepare-commit", response_model=VisualEditCommitPlan)
    def prepare_visual_edit_commit(session_id: str):
        """
        生成视觉编辑的提交计划。

        @params:
            session_id: 视觉编辑会话 ID

        @return:
            返回提交计划
        """
        try:
            return prepare_commit(session_id)
        except VisualEditNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"visual edit session not found: {session_id}") from exc
        except VisualEditRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/visual-edits/{session_id}/commit", response_model=VisualEditCommitResult)
    def commit_visual_edit_change(session_id: str, body: VisualEditCommitRequest | None = None):
        """
        提交当前视觉编辑确认过的文件。

        @params:
            session_id: 视觉编辑会话 ID
            body: 可选提交请求；force=True 时允许在存在其他脏文件时继续提交

        @return:
            返回提交结果
        """
        try:
            return commit_visual_edit(session_id, force=bool(body and body.force))
        except VisualEditNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"visual edit session not found: {session_id}") from exc
        except VisualEditRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.get("/demands", response_model=list[DemandListItem])
    def list_demands(engine=Depends(get_engine)):
        """
        直接读取飞书多维表格需求记录，并叠加当前进程内 runtime 状态。

        @params:
            engine: 由依赖注入提供的 engine facade

        @return:
            返回需求列表
        """
        runtime_states = engine.list_states()
        items: list[DemandListItem] = []
        for row in list_bitable_records():
            demand_id = row.get("demand_id") or row.get("record_id") or ""
            runtime = runtime_states.get(demand_id)
            if runtime:
                # 运行时状态优先于 Base 文本状态，避免列表页看到过期的中文列值。
                items.append(
                    DemandListItem(
                        id=runtime.id,
                        record_id=row.get("record_id") or runtime.id,
                        requirement=row.get("requirement") or runtime.requirement,
                        status=runtime.status,
                        current_stage=runtime.current_stage,
                        provider=runtime.provider,
                        template=runtime.template,
                        updated_at=runtime.updated_at,
                        doc_url=row.get("doc_url") or None,
                        tech_doc_url=row.get("tech_doc_url") or None,
                        runtime_available=True,
                    )
                )
                continue

            mapped_status, mapped_stage = _map_bitable_status(row.get("status") or "")
            items.append(
                DemandListItem(
                    id=demand_id,
                    record_id=row.get("record_id") or demand_id,
                    requirement=row.get("requirement") or row.get("doc_url") or "",
                    status=mapped_status,
                    current_stage=mapped_stage,
                    provider=None,
                    template=row.get("template") or "default",
                    updated_at=0,
                    doc_url=row.get("doc_url") or None,
                    tech_doc_url=row.get("tech_doc_url") or None,
                    runtime_available=False,
                )
            )
        return items

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
