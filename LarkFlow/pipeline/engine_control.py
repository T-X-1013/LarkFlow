"""Pipeline 生命周期控制：注册表 + 协作式 pause/resume/stop + 后台线程。

engine.py 在 `_run_phase` / `run_agent_loop` 的关键路径调用 `check_lifecycle()`，
当 pipeline 被标记 cancel 时抛出 `PipelineCancelled`，被标记 pause 时阻塞等待。

契约层 Stage (design/coding/test/review) ↔ engine phase (design/coding/testing/reviewing)
的映射也集中在此。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pipeline.contracts import (
    Checkpoint,
    CheckpointName,
    PipelineState,
    PipelineStatus,
    Stage,
    StageResult,
    StageStatus,
    TokenUsage,
)


# ==========================================
# Stage ↔ engine phase 映射
# ==========================================
# engine.py 内部历史命名为 testing/reviewing；契约对外命名 test/review
_STAGE_TO_PHASE: Dict[Stage, str] = {
    Stage.DESIGN: "design",
    Stage.CODING: "coding",
    Stage.TEST: "testing",
    Stage.REVIEW: "reviewing",
}
_PHASE_TO_STAGE: Dict[str, Stage] = {v: k for k, v in _STAGE_TO_PHASE.items()}


def stage_to_phase(stage: Stage) -> str:
    return _STAGE_TO_PHASE[stage]


def phase_to_stage(phase: str) -> Optional[Stage]:
    return _PHASE_TO_STAGE.get(phase)


# ==========================================
# 异常
# ==========================================
class PipelineCancelled(Exception):
    """pipeline 已被 stop，engine 路径上抛出以终止当前阶段。"""


# ==========================================
# Control block：每个 pipeline 一份
# ==========================================
@dataclass
class PipelineControl:
    demand_id: str
    requirement: str
    template: str = "default"
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    provider: Optional[str] = None
    thread: Optional[threading.Thread] = None
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    # pause_flag 被 set → 暂停；clear → 放行
    pause_flag: threading.Event = field(default_factory=threading.Event)
    # checkpoints / stage 结果缓存，D2 先跟 session 同步
    checkpoints: Dict[CheckpointName, Checkpoint] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = int(time.time())


# ==========================================
# 进程级注册表
# ==========================================
_REGISTRY: Dict[str, PipelineControl] = {}
_REGISTRY_LOCK = threading.Lock()


def register(
    requirement: str,
    template: str = "default",
    demand_id: Optional[str] = None,
) -> PipelineControl:
    did = demand_id or f"DEMAND-{uuid.uuid4().hex[:8]}"
    ctl = PipelineControl(demand_id=did, requirement=requirement, template=template)
    with _REGISTRY_LOCK:
        _REGISTRY[did] = ctl
    return ctl


def get(demand_id: str) -> Optional[PipelineControl]:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(demand_id)


def require(demand_id: str) -> PipelineControl:
    ctl = get(demand_id)
    if ctl is None:
        raise KeyError(f"pipeline {demand_id} not found")
    return ctl


def list_all() -> List[PipelineControl]:
    with _REGISTRY_LOCK:
        return list(_REGISTRY.values())


# ==========================================
# 协作式 lifecycle 检查（engine.py 关键路径调用）
# ==========================================
def check_lifecycle(demand_id: str) -> None:
    """engine 在关键点调用：若被 stop 则抛 PipelineCancelled，若 pause 则阻塞。

    未注册的 demand_id（例如旧入口 start_new_demand 直调）直接返回，不影响旧流程。
    """
    ctl = get(demand_id)
    if ctl is None:
        return
    if ctl.cancel_flag.is_set():
        raise PipelineCancelled(f"pipeline {demand_id} cancelled")
    # pause_flag.set 表示暂停。wait 一直阻塞直到 clear；期间可再被 cancel
    while ctl.pause_flag.is_set():
        if ctl.cancel_flag.wait(timeout=0.5):
            raise PipelineCancelled(f"pipeline {demand_id} cancelled while paused")


# ==========================================
# 生命周期动作
# ==========================================
def launch(ctl: PipelineControl, target, *args, **kwargs) -> None:
    """后台线程起 engine 入口（start_new_demand / resume_from_phase）。"""
    t = threading.Thread(
        target=target,
        args=args,
        kwargs=kwargs,
        name=f"pipeline-{ctl.demand_id}",
        daemon=True,
    )
    ctl.thread = t
    ctl.touch()
    t.start()


def pause(demand_id: str) -> PipelineControl:
    ctl = require(demand_id)
    ctl.pause_flag.set()
    ctl.touch()
    return ctl


def resume(demand_id: str) -> PipelineControl:
    ctl = require(demand_id)
    ctl.pause_flag.clear()
    ctl.touch()
    return ctl


def cancel(demand_id: str) -> PipelineControl:
    ctl = require(demand_id)
    ctl.cancel_flag.set()
    # 若处于 pause 中，解除阻塞让线程走到 cancel 分支退出
    ctl.pause_flag.clear()
    ctl.touch()
    return ctl


# ==========================================
# 状态反射：session + control → PipelineState
# ==========================================
_TERMINAL_PHASES = {"done", "failed"}


def _infer_status(ctl: PipelineControl, session_phase: Optional[str]) -> PipelineStatus:
    if ctl.cancel_flag.is_set():
        return PipelineStatus.STOPPED
    if session_phase == "failed":
        return PipelineStatus.FAILED
    if session_phase == "done":
        return PipelineStatus.SUCCEEDED
    # session_phase like "design_pending" 表示等审批
    if session_phase and session_phase.endswith("_pending"):
        return PipelineStatus.WAITING_APPROVAL
    # 检查任何已 rejected 的 checkpoint
    for cp in ctl.checkpoints.values():
        if cp.status == StageStatus.REJECTED:
            return PipelineStatus.REJECTED
    if ctl.pause_flag.is_set():
        return PipelineStatus.PAUSED
    if ctl.thread and ctl.thread.is_alive():
        return PipelineStatus.RUNNING
    if session_phase is None:
        return PipelineStatus.PENDING
    return PipelineStatus.RUNNING


def build_state(ctl: PipelineControl, session: Optional[Dict]) -> PipelineState:
    phase = (session or {}).get("phase") if session else None
    current_stage = phase_to_stage(phase) if phase else None

    stages: Dict[Stage, StageResult] = {}
    metrics = (session or {}).get("metrics") or {}
    # 以 engine 既有累计 metrics 做占位；D4 真实埋点补全
    if phase and current_stage:
        stages[current_stage] = StageResult(
            stage=current_stage,
            status=(
                StageStatus.SUCCESS
                if phase in _TERMINAL_PHASES
                else StageStatus.PENDING
            ),
            tokens=TokenUsage(
                input=int(metrics.get("input_tokens", 0) or 0),
                output=int(metrics.get("output_tokens", 0) or 0),
            ),
        )

    return PipelineState(
        id=ctl.demand_id,
        requirement=ctl.requirement,
        template=ctl.template,
        status=_infer_status(ctl, phase),
        current_stage=current_stage,
        stages=stages,
        checkpoints=dict(ctl.checkpoints),
        provider=ctl.provider,
        created_at=ctl.created_at,
        updated_at=ctl.updated_at,
    )
