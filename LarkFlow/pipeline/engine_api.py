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

from pipeline import engine, engine_control
from pipeline.contracts import (
    Checkpoint,
    CheckpointName,
    PipelineState,
    Stage,
    StageResult,
    StageStatus,
)
from pipeline.engine_control import PipelineControl


def _session(demand_id: str) -> Optional[Dict]:
    return engine.STORE.get(demand_id)


def _ctl(demand_id: str) -> PipelineControl:
    return engine_control.require(demand_id)


# ==========================================
# 9 个对外方法
# ==========================================
def create_pipeline(requirement: str, template: str = "default") -> PipelineState:
    ctl = engine_control.register(requirement=requirement, template=template)
    return engine_control.build_state(ctl, _session(ctl.demand_id))


def start(pipeline_id: str) -> PipelineState:
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
    engine_control.pause(pipeline_id)
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def resume(pipeline_id: str) -> PipelineState:
    engine_control.resume(pipeline_id)
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def stop(pipeline_id: str) -> PipelineState:
    engine_control.cancel(pipeline_id)
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def get_state(pipeline_id: str) -> PipelineState:
    return engine_control.build_state(_ctl(pipeline_id), _session(pipeline_id))


def get_stage_artifact(pipeline_id: str, stage: Stage) -> StageResult:
    state = get_state(pipeline_id)
    return state.stages.get(stage, StageResult(stage=stage, status=StageStatus.PENDING))


def approve_checkpoint(pipeline_id: str, checkpoint: CheckpointName) -> PipelineState:
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
    ctl = _ctl(pipeline_id)
    ctl.provider = provider
    ctl.touch()
    return engine_control.build_state(ctl, _session(pipeline_id))


def list_states() -> Dict[str, PipelineState]:
    return {
        ctl.demand_id: engine_control.build_state(ctl, _session(ctl.demand_id))
        for ctl in engine_control.list_all()
    }
