"""Pipeline IO 契约（D1 冻结，D4 起落到四阶段）。

字段严格对齐 V3 计划 §八 的 JSON 示例。对 tao/前端可见的所有端点响应
必须走这里的模型，禁止临时 dict。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==========================================
# Enum
# ==========================================
class Stage(str, Enum):
    DESIGN = "design"
    CODING = "coding"
    TEST = "test"
    REVIEW = "review"


class StageStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    PENDING = "pending"


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    STOPPED = "stopped"
    FAILED = "failed"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"


class CheckpointName(str, Enum):
    DESIGN = "design"      # 第 1 HITL：Design 产出审批
    DEPLOY = "deploy"      # 第 2 HITL：Review 通过后是否部署


class VisualEditSessionStatus(str, Enum):
    DRAFT = "draft"
    EDITING = "editing"
    PREVIEW_READY = "preview_ready"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ==========================================
# Stage / Pipeline 状态
# ==========================================
class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0


class StageResult(BaseModel):
    """§八 JSON 契约：阶段产物快照。"""

    stage: Stage
    status: StageStatus
    artifact_path: Optional[str] = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    duration_ms: int = 0
    errors: List[str] = Field(default_factory=list)


class Checkpoint(BaseModel):
    name: CheckpointName
    status: StageStatus = StageStatus.PENDING
    requested_at: Optional[int] = None
    resolved_at: Optional[int] = None
    reason: Optional[str] = None


class PipelineState(BaseModel):
    """Pipeline 运行态快照，GET /pipelines/{id} 直接返回。"""

    id: str
    requirement: str
    template: str = "default"
    status: PipelineStatus = PipelineStatus.PENDING
    current_stage: Optional[Stage] = None
    stages: Dict[Stage, StageResult] = Field(default_factory=dict)
    checkpoints: Dict[CheckpointName, Checkpoint] = Field(default_factory=dict)
    provider: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0


# ==========================================
# Request body
# ==========================================
class CreatePipelineRequest(BaseModel):
    requirement: str
    template: str = "default"


class CheckpointRejectRequest(BaseModel):
    reason: str


class ProviderUpdateRequest(BaseModel):
    provider: str  # anthropic | openai | doubao | qwen


class ElementRect(BaseModel):
    """圈选元素在当前视口中的矩形位置。"""

    top: int = 0
    left: int = 0
    width: int = 0
    height: int = 0


class VisualEditTarget(BaseModel):
    """视觉编辑圈选结果，既服务前端回显，也给后端做安全定位。"""

    lark_src: Optional[str] = None
    css_selector: str
    tag: str
    id: str = ""
    class_name: str = ""
    text: str = ""
    rect: Optional[ElementRect] = None


class VisualEditPreviewRequest(BaseModel):
    """创建视觉编辑预览时的请求体。"""

    requirement: str
    page_url: str
    page_path: str
    target: VisualEditTarget
    intent: str


class VisualEditSession(BaseModel):
    """视觉编辑会话快照，贯穿预览、确认、取消和提交流程。"""

    id: str
    requirement: str
    page_url: str
    page_path: str
    intent: str
    target: VisualEditTarget
    status: VisualEditSessionStatus = VisualEditSessionStatus.DRAFT
    preview_url: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    diff: Optional[str] = None
    diff_summary: List[str] = Field(default_factory=list)
    delivery_summary: Optional[str] = None
    confirmed_files: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: int = 0
    updated_at: int = 0


class VisualEditDeliveryCheck(BaseModel):
    """视觉编辑确认后的交付检查结果。"""

    session_id: str
    confirmed_files: List[str] = Field(default_factory=list)
    deliverable_files: List[str] = Field(default_factory=list)
    dirty_file_count: int = 0
    unrelated_dirty_count: int = 0
    safe_to_commit: bool = False


class VisualEditCommitPlan(BaseModel):
    """自动提交前的计划结果，供前端二次确认。"""

    session_id: str
    files: List[str] = Field(default_factory=list)
    commit_message: str = ""
    summary: str = ""
    safe_to_commit: bool = False
    requires_manual_confirmation: bool = True
    warnings: List[str] = Field(default_factory=list)


class VisualEditCommitRequest(BaseModel):
    """视觉编辑提交请求。"""

    force: bool = False


class VisualEditCommitResult(BaseModel):
    """视觉编辑提交结果。"""

    session_id: str
    commit_hash: Optional[str] = None
    commit_message: str = ""
    committed_files: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ==========================================
# Response
# ==========================================
class PipelineCreateResponse(BaseModel):
    id: str


class MetricsItem(BaseModel):
    pipeline_id: str
    status: PipelineStatus
    duration_ms: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    stages: Dict[Stage, StageResult] = Field(default_factory=dict)


class MetricsResponse(BaseModel):
    pipelines: List[MetricsItem] = Field(default_factory=list)


class ArtifactResponse(BaseModel):
    stage: Stage
    artifact_path: str
    content: Optional[str] = None


class Ack(BaseModel):
    """通用 ack 返回。"""

    ok: bool = True
    detail: Optional[Dict[str, Any]] = None
