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

from pipeline.core.contracts import (
    Checkpoint,
    CheckpointName,
    PipelineState,
    PipelineStatus,
    Stage,
    StageResult,
    StageStatus,
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
    """
    把契约层阶段枚举转换为 engine 内部 phase 名称。

    @params:
        stage: 对外阶段枚举

    @return:
        返回 engine 使用的 phase 字符串
    """
    return _STAGE_TO_PHASE[stage]


def phase_to_stage(phase: str) -> Optional[Stage]:
    """
    把 engine phase 名称映射回对外阶段枚举。

    @params:
        phase: engine 内部 phase 字符串

    @return:
        返回对应 Stage；未知 phase 时返回 None
    """
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
    """单条 Pipeline 的进程内控制块。"""

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
        """刷新控制块更新时间，供列表和状态接口反映最近操作。"""
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
    """
    注册一条新的 Pipeline 控制块。

    @params:
        requirement: 需求文本
        template: 模板名
        demand_id: 可选指定 demand_id；为空时自动生成

    @return:
        返回注册后的 PipelineControl
    """
    did = demand_id or f"DEMAND-{uuid.uuid4().hex[:8]}"
    ctl = PipelineControl(demand_id=did, requirement=requirement, template=template)
    with _REGISTRY_LOCK:
        _REGISTRY[did] = ctl
    return ctl


def get(demand_id: str) -> Optional[PipelineControl]:
    """
    读取指定需求的控制块。

    @params:
        demand_id: 需求 ID

    @return:
        返回 PipelineControl；不存在时返回 None
    """
    with _REGISTRY_LOCK:
        return _REGISTRY.get(demand_id)


def require(demand_id: str) -> PipelineControl:
    """
    强制读取指定需求的控制块。

    @params:
        demand_id: 需求 ID

    @return:
        返回 PipelineControl；不存在时抛出 KeyError
    """
    ctl = get(demand_id)
    if ctl is None:
        raise KeyError(f"pipeline {demand_id} not found")
    return ctl


def list_all() -> List[PipelineControl]:
    """
    枚举当前注册表中的全部控制块。

    @params:
        无

    @return:
        返回 PipelineControl 列表快照
    """
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
    """
    标记指定 Pipeline 为暂停态。

    @params:
        demand_id: 需求 ID

    @return:
        返回更新后的 PipelineControl
    """
    ctl = require(demand_id)
    ctl.pause_flag.set()
    ctl.touch()
    return ctl


def resume(demand_id: str) -> PipelineControl:
    """
    清除指定 Pipeline 的暂停态。

    @params:
        demand_id: 需求 ID

    @return:
        返回更新后的 PipelineControl
    """
    ctl = require(demand_id)
    ctl.pause_flag.clear()
    ctl.touch()
    return ctl


def cancel(demand_id: str) -> PipelineControl:
    """
    标记指定 Pipeline 为停止态，并唤醒可能阻塞的线程。

    @params:
        demand_id: 需求 ID

    @return:
        返回更新后的 PipelineControl
    """
    ctl = require(demand_id)
    ctl.cancel_flag.set()
    # 若处于 pause 中，解除阻塞让线程走到 cancel 分支退出
    ctl.pause_flag.clear()
    ctl.touch()
    return ctl


# ==========================================
# 状态反射：session + control → PipelineState
# ==========================================
def _infer_status(ctl: PipelineControl, session_phase: Optional[str]) -> PipelineStatus:
    """
    综合控制块和 session phase 推导对外 PipelineStatus。

    @params:
        ctl: 进程内控制块
        session_phase: session 中记录的当前 phase

    @return:
        返回对外暴露的 PipelineStatus
    """
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
    """
    把运行时控制块与持久化 session 组装成契约层状态快照。

    @params:
        ctl: 进程内控制块
        session: 可选 session 字典

    @return:
        返回供 REST/前端消费的 PipelineState
    """
    phase = (session or {}).get("phase") if session else None
    current_stage = phase_to_stage(phase) if phase else None
    # *_pending / deploying 不是正式 stage 名称，需要额外映射回用户可理解的阶段。
    if current_stage is None and phase and phase.endswith("_pending"):
        pending_phase = phase.removesuffix("_pending")
        if pending_phase == "design":
            current_stage = Stage.DESIGN
        elif pending_phase == "deploy":
            current_stage = Stage.REVIEW
    if current_stage is None and phase == "deploying":
        current_stage = Stage.REVIEW

    # D4：从 session["stage_results"] 反序列化真实 StageResult。
    # 不存在时返回空 dict；不合法条目跳过，不阻塞状态查询。
    stages: Dict[Stage, StageResult] = {}
    raw_stages = (session or {}).get("stage_results") or {}
    for stage_key, payload in raw_stages.items():
        try:
            stage_enum = Stage(stage_key)
        except ValueError:
            continue
        try:
            stages[stage_enum] = StageResult(**payload)
        except Exception:  # noqa: BLE001 — 数据损坏不应拖垮 API
            continue

    # D7：feature_multi 等 parallel review 模板把三路 reviewer 的结果落在
    # session["review_multi"]["subroles"]，反序列化为 ReviewMultiSnapshot；
    # 单 agent 模板无此字段，review_multi 保持 None（前端判空不渲染）。
    review_multi = None
    raw_review_multi = (session or {}).get("review_multi") or {}
    raw_subroles = raw_review_multi.get("subroles") or []
    if raw_subroles:
        from pipeline.core.contracts import ReviewMultiSnapshot, ReviewSubRoleResult
        parsed: list = []
        for entry in raw_subroles:
            if not isinstance(entry, dict):
                continue
            try:
                parsed.append(ReviewSubRoleResult(
                    role=str(entry.get("role", "")),
                    status=str(entry.get("status", "pending")),
                    artifact_path=entry.get("artifact_path"),
                    tokens_input=int(entry.get("tokens_input", 0) or 0),
                    tokens_output=int(entry.get("tokens_output", 0) or 0),
                    duration_ms=int(entry.get("duration_ms", 0) or 0),
                    error=entry.get("error"),
                ))
            except Exception:  # noqa: BLE001 — 损坏条目不阻塞状态查询
                continue
        if parsed:
            review_multi = ReviewMultiSnapshot(subroles=parsed)

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
        review_multi=review_multi,
    )
