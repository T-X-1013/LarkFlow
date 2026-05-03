"""Engine facade：REST/WS 调用的 9 个方法。

D1 为内存占位，D2 起接入真实 engine：
- create_pipeline：注册 control + 预留 session
- start：后台线程跑 engine.start_new_demand
- pause/resume/stop：协作式控制 engine_control flag
- approve/reject_checkpoint：走 engine.resume_after_approval（design HITL），
    deploy HITL 的分发 D3 再接
- get_state：SessionStore + control → PipelineState
"""
from __future__ import annotations

from typing import Dict, Optional

from pipeline.core import engine, engine_control
from pipeline.core.contracts import (
    Checkpoint,
    CheckpointName,
    MetricsItem,
    PipelineState,
    Stage,
    StageResult,
    StageStatus,
)
from pipeline.core.engine_control import PipelineControl
from pipeline.llm.adapter import validate_provider_name
from pipeline.ops.observability import build_metrics_item


def _session(demand_id: str) -> Optional[Dict]:
    """
    读取指定需求的持久化 session。

    @params:
        demand_id: 需求 ID

    @return:
        返回 session 字典；不存在时返回 None
    """
    return engine.STORE.get(demand_id)


def _ctl(demand_id: str) -> PipelineControl:
    """
    读取指定需求的运行时控制对象。

    @params:
        demand_id: 需求 ID

    @return:
        返回 PipelineControl；不存在时抛出异常
    """
    return engine_control.require(demand_id)


# ==========================================
# 9 个对外方法
# ==========================================
def create_pipeline(requirement: str, template: str = "default") -> PipelineState:
    """
    创建一条新的 Pipeline 控制记录。

    @params:
        requirement: 需求文本
        template: 可选模板名

    @return:
        返回新建后的 PipelineState
    """
    ctl = engine_control.register(requirement=requirement, template=template)
    return engine_control.build_state(ctl, _session(ctl.demand_id))


def start(pipeline_id: str) -> PipelineState:
    """
    启动指定 Pipeline 的后台执行线程。

    @params:
        pipeline_id: 目标 Pipeline ID

    @return:
        返回启动后的最新 PipelineState
    """
    ctl = _ctl(pipeline_id)
    if ctl.thread and ctl.thread.is_alive():
        return engine_control.build_state(ctl, _session(pipeline_id))
    engine_control.launch(
        ctl,
        engine.start_new_demand,
        ctl.demand_id,
        ctl.requirement,
        None,  # record_id
    )
    return engine_control.build_state(ctl, _session(pipeline_id))


def pause(pipeline_id: str) -> PipelineState:
    """
    暂停指定 Pipeline。

    @params:
        pipeline_id: 目标 Pipeline ID

    @return:
        返回暂停后的最新 PipelineState
    """
    engine_control.pause(pipeline_id)
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def resume(pipeline_id: str) -> PipelineState:
    """
    恢复指定 Pipeline。

    @params:
        pipeline_id: 目标 Pipeline ID

    @return:
        返回恢复后的最新 PipelineState
    """
    engine_control.resume(pipeline_id)
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def stop(pipeline_id: str) -> PipelineState:
    """
    停止指定 Pipeline。

    @params:
        pipeline_id: 目标 Pipeline ID

    @return:
        返回停止后的最新 PipelineState
    """
    engine_control.cancel(pipeline_id)
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def get_state(pipeline_id: str) -> PipelineState:
    """
    读取指定 Pipeline 的状态快照。

    @params:
        pipeline_id: 目标 Pipeline ID

    @return:
        返回最新 PipelineState
    """
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def get_stage_artifact(pipeline_id: str, stage: Stage) -> StageResult:
    """
    查询指定阶段的产物信息。

    @params:
        pipeline_id: 目标 Pipeline ID
        stage: 目标阶段

    @return:
        返回对应阶段的 StageResult；不存在时返回 pending 占位
    """
    state = get_state(pipeline_id)
    return state.stages.get(stage, StageResult(stage=stage, status=StageStatus.PENDING))


def approve_checkpoint(pipeline_id: str, checkpoint: CheckpointName) -> PipelineState:
    """
    通过指定检查点，并触发后续状态推进。

    @params:
        pipeline_id: 目标 Pipeline ID
        checkpoint: 检查点名称

    @return:
        返回审批后的最新 PipelineState
    """
    ctl = _ctl(pipeline_id)
    cp = ctl.checkpoints.setdefault(checkpoint, Checkpoint(name=checkpoint))
    cp.status = StageStatus.SUCCESS
    import time as _t
    cp.resolved_at = int(_t.time())
    ctl.touch()

    if checkpoint == CheckpointName.DESIGN:
        # 复用现有审批闭环：推进到 coding
        engine_control.launch(
            ctl,
            engine.resume_after_approval,
            pipeline_id,
            True,   # approved
            "",    # feedback
        )
    elif checkpoint == CheckpointName.DEPLOY:
        # 第 2 HITL：真正触发部署（后台线程内跑 deploy_app，保证 REST/WS 调用不阻塞）
        engine_control.launch(ctl, engine.trigger_deploy, pipeline_id)

    return engine_control.build_state(ctl, _session(pipeline_id))


def reject_checkpoint(
    pipeline_id: str, checkpoint: CheckpointName, reason: str
) -> PipelineState:
    """
    驳回指定检查点，并记录驳回原因。

    @params:
        pipeline_id: 目标 Pipeline ID
        checkpoint: 检查点名称
        reason: 驳回原因

    @return:
        返回驳回后的最新 PipelineState
    """
    ctl = _ctl(pipeline_id)
    cp = ctl.checkpoints.setdefault(checkpoint, Checkpoint(name=checkpoint))
    cp.status = StageStatus.REJECTED
    cp.reason = reason
    import time as _t
    cp.resolved_at = int(_t.time())
    ctl.touch()

    if checkpoint == CheckpointName.DESIGN:
        engine_control.launch(
            ctl,
            engine.resume_after_approval,
            pipeline_id,
            False,  # rejected
            reason,
        )
    # deploy rejected 直接 stop，不发部署
    elif checkpoint == CheckpointName.DEPLOY:
        engine_control.cancel(pipeline_id)

    return engine_control.build_state(ctl, _session(pipeline_id))


def set_provider(pipeline_id: str, provider: str) -> PipelineState:
    """
    在 Pipeline 启动前设置大模型 Provider。

    @params:
        pipeline_id: 目标 Pipeline ID
        provider: 待设置的 provider 名称

    @return:
        返回更新后的最新 PipelineState
    """
    ctl = _ctl(pipeline_id)
    if _session(pipeline_id) is not None or (ctl.thread and ctl.thread.is_alive()):
        raise RuntimeError(
            f"pipeline {pipeline_id} already started; provider can only be changed before start"
        )

    ctl.provider = validate_provider_name(provider)
    ctl.touch()
    return engine_control.build_state(ctl, _session(pipeline_id))


def list_metrics() -> list[MetricsItem]:
    """
    汇总所有 Pipeline 的指标数据。

    @params:
        无

    @return:
        返回 MetricsItem 列表
    """
    items: list[MetricsItem] = []
    for ctl in engine_control.list_all():
        session = _session(ctl.demand_id)
        state = engine_control.build_state(ctl, session)
        items.append(build_metrics_item(ctl.demand_id, state, session))
    return items


def list_pipelines() -> list[PipelineState]:
    """
    列出当前全部 Pipeline 状态快照，供列表页消费。

    @return:
        返回 PipelineState 列表（按 control 注册表顺序）
    """
    return list(list_states().values())


def list_states() -> Dict[str, PipelineState]:
    """
    读取当前全部 Pipeline 的状态快照。

    @params:
        无

    @return:
        返回以 demand_id 为键的状态字典
    """
    return {
        ctl.demand_id: engine_control.build_state(ctl, _session(ctl.demand_id))
        for ctl in engine_control.list_all()
    }
