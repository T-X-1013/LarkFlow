"""Phase 0：需求规范化。

把自然语言需求解析成结构化 NormalizedDemand，供下游：
1. SkillRouter 使用结构化字段（apis / persistence / nfr）触发 Tier-1 必读；
2. Phase 1 设计 agent 以结构化需求为权威输入，而非原始 NL；
3. 前端渲染核对卡片；澄清回路（后续 PR）在这里落。
"""

from pipeline.phase0.normalizer import normalize_demand
from pipeline.phase0.schema import (
    ApiSketch,
    NfrFlags,
    NormalizedDemand,
    OpenQuestion,
    PersistenceHint,
)

__all__ = [
    "ApiSketch",
    "NfrFlags",
    "NormalizedDemand",
    "OpenQuestion",
    "PersistenceHint",
    "normalize_demand",
]
