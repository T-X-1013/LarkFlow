"""Skill 闸门：确保 Phase 2 结束前，命中清单里的强约束 skill 已全部被 read 过。

分 tier 处理：
- baseline / conditional → mandatory：缺 → 闸门失败，engine 会追加一轮让 agent 补读。
- route → optional：缺 → 只打告警标记，不 block。

闸门结果以 `SkillGateVerdict` 形式返回，同时写进 session["skill_gate"]，REST 透传
给前端，便于 reviewer 一眼看出哪条 skill 没被真实读到。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

_LOG = logging.getLogger("larkflow.skill_gate")

_ENV_ENABLED = "LARKFLOW_SKILL_GATE_ENABLED"
_ENV_MAX_RETRIES = "LARKFLOW_SKILL_GATE_MAX_RETRIES"
_DEFAULT_MAX_RETRIES = 2

_MANDATORY_TIERS = {"baseline", "conditional"}


@dataclass
class SkillGateVerdict:
    """闸门一次判读的结果。"""

    passed: bool
    missing_mandatory: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    read: list[str] = field(default_factory=list)
    attempt: int = 1              # 第几次判读（从 1 开始）

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "missing_mandatory": list(self.missing_mandatory),
            "missing_optional": list(self.missing_optional),
            "read": list(self.read),
            "attempt": self.attempt,
        }

    def render_remediation_message(self) -> str:
        """生成一段要追加给 agent 的 user message，让它把缺的 mandatory skill 补读完。"""
        if not self.missing_mandatory:
            return ""
        lines = [
            "⚠️ Skill 闸门未通过：以下强约束 skill 尚未使用 `file_editor` action=read 读取过，",
            "在继续产出代码前，请先逐条读取它们，然后再恢复原任务。",
            "",
        ]
        for skill in self.missing_mandatory:
            lines.append(f"- `{skill}`")
        if self.missing_optional:
            lines.append("")
            lines.append(
                "提示：以下 Tier-2 skill 也在权威清单里，建议一并读取，但本轮不强制："
            )
            for skill in self.missing_optional:
                lines.append(f"- `{skill}`")
        return "\n".join(lines)


def is_enabled() -> bool:
    """env 开关：默认启用；设成 0/false/no 显式关闭。"""
    val = os.getenv(_ENV_ENABLED, "1").strip().lower()
    return val not in {"0", "false", "no", "off", ""}


def max_retries() -> int:
    """闸门追加轮次上限；非法值回落默认。"""
    raw = os.getenv(_ENV_MAX_RETRIES, "").strip()
    if not raw:
        return _DEFAULT_MAX_RETRIES
    try:
        val = int(raw)
    except ValueError:
        return _DEFAULT_MAX_RETRIES
    return max(0, val)


def check_coverage(
    skill_routing: Optional[dict[str, Any]],
    skills_read: Optional[Iterable[str]],
    *,
    attempt: int = 1,
) -> SkillGateVerdict:
    """对比路由清单与实际已读集合，输出闸门判读。

    @params:
        skill_routing : session["skill_routing"]（to_dict 产物）或 None
        skills_read   : session["skills_read"]（已读相对路径列表）或 None
        attempt       : 第几轮调用（engine 触发重试时递增）

    @return:
        SkillGateVerdict：passed=True 当且仅当 mandatory 为空。
    """
    routing = skill_routing or {}
    reasons = routing.get("reasons") or []
    mandatory: list[str] = []
    optional: list[str] = []
    mandatory_seen: set[str] = set()
    optional_seen: set[str] = set()
    for reason in reasons:
        if not isinstance(reason, dict):
            continue
        skill = str(reason.get("skill", "") or "")
        tier = str(reason.get("tier", "") or "")
        if not skill:
            continue
        if tier in _MANDATORY_TIERS:
            if skill not in mandatory_seen:
                mandatory.append(skill)
                mandatory_seen.add(skill)
        elif tier == "route":
            if skill not in optional_seen:
                optional.append(skill)
                optional_seen.add(skill)

    read_set = {str(s) for s in (skills_read or []) if s}
    missing_mandatory = [s for s in mandatory if s not in read_set]
    missing_optional = [s for s in optional if s not in read_set]
    passed = not missing_mandatory

    return SkillGateVerdict(
        passed=passed,
        missing_mandatory=missing_mandatory,
        missing_optional=missing_optional,
        read=sorted(read_set),
        attempt=attempt,
    )
