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
