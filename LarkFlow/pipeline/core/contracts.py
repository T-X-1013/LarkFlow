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
    """Pipeline 对外暴露的四阶段枚举。"""

    DESIGN = "design"
    CODING = "coding"
    TEST = "test"
    REVIEW = "review"


class StageStatus(str, Enum):
    """阶段产出或检查点的通用状态枚举。"""

    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    PENDING = "pending"


class PipelineStatus(str, Enum):
    """Pipeline 整体运行态枚举，供 REST 和前端统一消费。"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    STOPPED = "stopped"
    FAILED = "failed"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"


class CheckpointName(str, Enum):
    """人工审批检查点名称。"""

    DESIGN = "design"      # 第 1 HITL：Design 产出审批
    DEPLOY = "deploy"      # 第 2 HITL：Review 通过后是否部署


class VisualEditSessionStatus(str, Enum):
    """视觉编辑会话生命周期状态。"""

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
    """单个阶段或整条 Pipeline 的 token 消耗。"""

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
    """单个 HITL 检查点的审批状态。"""

    name: CheckpointName
    status: StageStatus = StageStatus.PENDING
    requested_at: Optional[int] = None
    resolved_at: Optional[int] = None
    reason: Optional[str] = None


class ReviewSubRoleResult(BaseModel):
    """D7：Phase 4 多视角并行 Review 单个 role 的快照。

    非主契约（stages[review] 仍为单条 StageResult），此字段仅在模板
    声明了 parallel review 时才非空，供前端仪表盘按 role 拆 token / duration。
    """

    role: str
    status: str = "pending"  # done | failed | cancelled | pending
    artifact_path: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    duration_ms: int = 0
    error: Optional[str] = None


class ReviewMultiSnapshot(BaseModel):
    """Phase 4 并行 Review 的 subroles 汇总。"""

    subroles: List[ReviewSubRoleResult] = Field(default_factory=list)


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
    # D7：多视角并行 Review 的补充信息。仅 feature_multi 等声明 parallel_review
    # 的模板会写入；前端判 None 不渲染，保证向后兼容。
    review_multi: Optional[ReviewMultiSnapshot] = None


class DemandListItem(BaseModel):
    """多维表格需求列表项；前端列表页直接消费。"""

    id: str
    record_id: str
    requirement: str
    status: PipelineStatus = PipelineStatus.PENDING
    current_stage: Optional[Stage] = None
    provider: Optional[str] = None
    template: str = "default"
    updated_at: int = 0
    doc_url: Optional[str] = None
    tech_doc_url: Optional[str] = None
    runtime_available: bool = False


# ==========================================
# Request body
# ==========================================
class CreatePipelineRequest(BaseModel):
    """创建 Pipeline 的请求体。"""

    requirement: str
    template: str = "default"


class CheckpointRejectRequest(BaseModel):
    """驳回检查点时的请求体。"""

    reason: str


class ProviderUpdateRequest(BaseModel):
    """启动前切换模型 provider 的请求体。"""

    provider: str  # anthropic | openai | doubao | qwen


class ElementRect(BaseModel):
    """圈选元素在当前视口中的矩形位置。"""

    top: int = 0
    left: int = 0
    width: int = 0
    height: int = 0


class ElementStyleSnapshot(BaseModel):
    """运行时样式快照，用于参照式视觉编辑。"""

    color: str = ""
    backgroundColor: str = ""
    fontSize: str = ""
    fontWeight: str = ""


class VisualEditContextNode(BaseModel):
    """圈选元素附近的参照节点。"""

    relation: str
    tag: str
    text: str = ""
    css_selector: str
    id: str = ""
    class_name: str = ""
    style: ElementStyleSnapshot = Field(default_factory=ElementStyleSnapshot)


class VisualEditTargetContext(BaseModel):
    """前后文节点集合，辅助理解相对描述。"""

    previous: Optional[VisualEditContextNode] = None
    next: Optional[VisualEditContextNode] = None
    parent: Optional[VisualEditContextNode] = None


class VisualEditTarget(BaseModel):
    """视觉编辑圈选结果，既服务前端回显，也给后端做安全定位。"""

    lark_src: Optional[str] = None
    css_selector: str
    tag: str
    id: str = ""
    class_name: str = ""
    text: str = ""
    rect: Optional[ElementRect] = None
    context: Optional[VisualEditTargetContext] = None
    reference: Optional[VisualEditContextNode] = None


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
    """创建 Pipeline 后返回的最小响应。"""

    id: str


class RoleMetrics(BaseModel):
    """D7：按 role 拆分的 tokens / duration，供仪表盘画饼图。"""

    role: str
    tokens_input: int = 0
    tokens_output: int = 0
    duration_ms: int = 0


class MetricsItem(BaseModel):
    """单条 Pipeline 的指标快照。"""

    pipeline_id: str
    status: PipelineStatus
    duration_ms: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    stages: Dict[Stage, StageResult] = Field(default_factory=dict)
    # D7：feature_multi 模板下 Phase 4 每 role 的 tokens / duration；
    # 非 parallel review 时为空列表，前端判空不渲染。
    by_role: List[RoleMetrics] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    """指标列表接口响应。"""

    pipelines: List[MetricsItem] = Field(default_factory=list)


class ArtifactResponse(BaseModel):
    """阶段产物查询响应。"""

    stage: Stage
    artifact_path: str
    content: Optional[str] = None


class Ack(BaseModel):
    """通用 ack 返回。"""

    ok: bool = True
    detail: Optional[Dict[str, Any]] = None
