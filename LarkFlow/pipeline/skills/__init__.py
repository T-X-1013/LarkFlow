"""pipeline.skills: 方案 A+D 的 skill 路由与 feedback 闭环。

resolver: Phase1 tech_tags → 注入给 Phase2/4 的 skill 清单
feedback: Phase4 <skill-feedback> XML 块落盘
"""
from .resolver import (
    MatchReason,
    SkillRouting,
    load_table,
    render_for_prompt,
    resolve,
    valid_tags,
)
from .feedback import capture_feedback, parse_feedback_blocks

__all__ = [
    "MatchReason",
    "SkillRouting",
    "capture_feedback",
    "load_table",
    "parse_feedback_blocks",
    "render_for_prompt",
    "resolve",
    "valid_tags",
]
