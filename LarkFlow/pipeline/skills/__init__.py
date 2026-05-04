"""Skill routing 模块：把需求文本映射到必读 skill 列表。"""

from pipeline.skills.gate import SkillGateVerdict, check_coverage
from pipeline.skills.router import (
    MatchReason,
    SkillRouting,
    load_routing_table,
    route_from_text,
)

__all__ = [
    "MatchReason",
    "SkillRouting",
    "SkillGateVerdict",
    "check_coverage",
    "load_routing_table",
    "route_from_text",
]
