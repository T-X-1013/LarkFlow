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
from typing import Any, Dict, List, Optional

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
def _infer_status(ctl: PipelineControl, session_phase: Optional[str]) -> PipelineStatus:
    if ctl.cancel_flag.is_set():
        return PipelineStatus.STOPPED
    if session_phase == "failed":
        return PipelineStatus.FAILED
    if session_phase == "done":
        return PipelineStatus.SUCCEEDED
    # Phase 0 澄清挂起有独立状态，与 design/deploy 的 waiting_approval 区分开
    if session_phase == "clarification_pending":
        return PipelineStatus.WAITING_CLARIFICATION
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

    # PR-5：session["skill_routing"] 由 start_new_demand 一次性计算并落盘，
    # 这里直接反序化为 Pydantic 契约。字段缺失或损坏不阻塞查询，保持 None。
    skill_routing = _parse_skill_routing((session or {}).get("skill_routing"))
    skill_gate = _parse_skill_gate((session or {}).get("skill_gate"))
    normalized_demand = _parse_normalized_demand((session or {}).get("normalized_demand"))

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
        skill_routing=skill_routing,
        skill_gate=skill_gate,
        normalized_demand=normalized_demand,
    )


def _parse_normalized_demand(raw: Any) -> Optional["NormalizedDemandSnapshot"]:
    """反序化 session["normalized_demand"]；异常返回 None。"""
    if not isinstance(raw, dict):
        return None
    from pipeline.core.contracts import (
        ApiSketchSnapshot,
        NfrSnapshot,
        NormalizedDemandSnapshot,
        OpenQuestionSnapshot,
        PersistenceSnapshot,
    )
    try:
        persistence = raw.get("persistence") or {}
        nfr = raw.get("nfr") or {}
        return NormalizedDemandSnapshot(
            raw_demand=str(raw.get("raw_demand", "") or ""),
            goal=str(raw.get("goal", "") or ""),
            out_of_scope=[str(x) for x in (raw.get("out_of_scope") or []) if x],
            entities=[str(x) for x in (raw.get("entities") or []) if x],
            apis=[
                ApiSketchSnapshot(
                    method=str(a.get("method", "") or ""),
                    path=str(a.get("path", "") or ""),
                    purpose=str(a.get("purpose", "") or ""),
                )
                for a in (raw.get("apis") or [])
                if isinstance(a, dict)
            ],
            persistence=PersistenceSnapshot(
                needs_storage=bool(persistence.get("needs_storage")),
                needs_migration=bool(persistence.get("needs_migration")),
                tables=[str(t) for t in (persistence.get("tables") or []) if t],
                notes=str(persistence.get("notes", "") or ""),
            ),
            nfr=NfrSnapshot(
                auth=bool(nfr.get("auth")),
                idempotent=bool(nfr.get("idempotent")),
                rate_limit=bool(nfr.get("rate_limit")),
                transactional=bool(nfr.get("transactional")),
                high_concurrency=bool(nfr.get("high_concurrency")),
            ),
            domain_tags=[str(x) for x in (raw.get("domain_tags") or []) if x],
            touches_python=bool(raw.get("touches_python")),
            open_questions=[
                OpenQuestionSnapshot(
                    text=str(q.get("text", "") or ""),
                    blocking=bool(q.get("blocking")),
                    candidates=[str(c) for c in (q.get("candidates") or []) if c],
                )
                for q in (raw.get("open_questions") or [])
                if isinstance(q, dict)
            ],
            confidence=float(raw.get("confidence", 1.0) or 0.0),
            source=str(raw.get("source", "rule") or "rule"),
        )
    except Exception:  # noqa: BLE001
        return None


def _parse_skill_gate(raw: Any) -> Optional["SkillGateSnapshot"]:
    """反序化 session["skill_gate"]；异常返回 None。"""
    if not isinstance(raw, dict):
        return None
    from pipeline.core.contracts import SkillGateSnapshot
    try:
        return SkillGateSnapshot(
            passed=bool(raw.get("passed", True)),
            missing_mandatory=[str(s) for s in (raw.get("missing_mandatory") or []) if s],
            missing_optional=[str(s) for s in (raw.get("missing_optional") or []) if s],
            read=[str(s) for s in (raw.get("read") or []) if s],
            attempt=int(raw.get("attempt", 1) or 1),
        )
    except Exception:  # noqa: BLE001
        return None


def _parse_skill_routing(raw: Any) -> Optional["SkillRoutingSnapshot"]:
    """把 session 里存的 dict 反序化为 SkillRoutingSnapshot；缺字段返回 None。"""
    if not isinstance(raw, dict):
        return None
    skills = [str(s) for s in (raw.get("skills") or []) if s]
    reasons_raw = raw.get("reasons") or []
    if not skills and not reasons_raw:
        return None
    from pipeline.core.contracts import SkillRoutingReason, SkillRoutingSnapshot
    reasons: list[SkillRoutingReason] = []
    for entry in reasons_raw:
        if not isinstance(entry, dict):
            continue
        try:
            reasons.append(
                SkillRoutingReason(
                    skill=str(entry.get("skill", "")),
                    tier=str(entry.get("tier", "")),
                    detail=str(entry.get("detail", "") or ""),
                    score=float(entry.get("score", 0.0) or 0.0),
                    source=str(entry.get("source", "") or ""),
                )
            )
        except Exception:  # noqa: BLE001 — 损坏条目不阻塞状态查询
            continue
    return SkillRoutingSnapshot(skills=skills, reasons=reasons)
