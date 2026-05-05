"""Skill resolver: 把 Phase1 产出的 tech_tags 映射成要注入给 Phase2/4 的 skill 清单。

数据流：
  Phase1 ask_human_approval(tech_tags={domains, capabilities, rationale})
    → resolve(tech_tags, design_doc) → SkillRouting
    → render_for_prompt(routing) 拼到下一阶段 system prompt 顶部

设计原则：
- YAML (`rules/skill-routing.yaml`) 是唯一数据源。tag 合法值 = YAML 里每条 route 的 skill 文件 stem。
- 标签合法 → 直接映射；标签非法或整体缺失 → 回退到旧行为（关键词子串匹配）。
- defaults 列表（YAML 里既有字段）始终合并，作为 baseline，保证 kratos.md 等永远在场。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

_LOG = logging.getLogger("larkflow.skill_resolver")

# rules/skill-routing.yaml 相对 workspace_root 的路径；workspace_root = LarkFlow/
_DEFAULT_YAML_PATH = (
    Path(__file__).resolve().parents[2] / "rules" / "skill-routing.yaml"
)


@dataclass
class MatchReason:
    skill: str                 # 例：skills/domain/user.md
    tier: str                  # "tag" | "fallback" | "default"
    detail: str                # 命中的 tag id / 匹配到的关键词 / "baseline"
    rationale: str = ""        # 来自 tech_tags.rationale[tag]，可空


@dataclass
class SkillRouting:
    skills: List[str] = field(default_factory=list)
    reasons: List[MatchReason] = field(default_factory=list)
    source: str = "tags"       # "tags" | "fallback" | "empty"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skills": list(self.skills),
            "reasons": [
                {"skill": r.skill, "tier": r.tier, "detail": r.detail, "rationale": r.rationale}
                for r in self.reasons
            ],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["SkillRouting"]:
        if not data:
            return None
        reasons = [
            MatchReason(
                skill=r.get("skill", ""),
                tier=r.get("tier", ""),
                detail=r.get("detail", ""),
                rationale=r.get("rationale", ""),
            )
            for r in data.get("reasons", [])
        ]
        return cls(
            skills=list(data.get("skills", [])),
            reasons=reasons,
            source=data.get("source", "tags"),
        )


@dataclass(frozen=True)
class _RoutingTable:
    routes: List[Dict[str, Any]]
    defaults: List[str]
    by_stem: Dict[str, str]    # tag id → skill path
    weights: Dict[str, float]  # skill path → weight（用于排序，缺省 1.0）


def _skill_stem(path: str) -> str:
    """skills/domain/user.md → user"""
    return Path(path).stem


def load_table(yaml_path: Optional[Path] = None) -> _RoutingTable:
    path = yaml_path or _DEFAULT_YAML_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    routes = list(raw.get("routes") or [])
    defaults = list(raw.get("defaults") or [])

    by_stem: Dict[str, str] = {}
    weights: Dict[str, float] = {}
    for route in routes:
        skill = route.get("skill")
        if not skill:
            continue
        try:
            w = float(route.get("weight", 1.0) or 1.0)
        except (TypeError, ValueError):
            w = 1.0
        # 同一 skill 多条 route 命中时，保留最高权重
        if skill not in weights or w > weights[skill]:
            weights[skill] = w
        stem = _skill_stem(skill)
        # stem 冲突（两条 route 指向同名文件）以先出现者为准并记 WARN
        if stem in by_stem and by_stem[stem] != skill:
            _LOG.warning(
                "skill stem collision: %s -> %s (already %s); keeping first",
                stem, skill, by_stem[stem],
            )
            continue
        by_stem[stem] = skill
    return _RoutingTable(routes=routes, defaults=defaults, by_stem=by_stem, weights=weights)


def valid_tags(table: Optional[_RoutingTable] = None) -> List[str]:
    """所有合法 tag id（升序），给 Phase1 prompt / 文档生成用。"""
    t = table or load_table()
    return sorted(t.by_stem.keys())


def _match_keywords(design_doc: str, table: _RoutingTable) -> List[MatchReason]:
    """旧行为：对 design_doc 做大小写无关的子串关键词匹配。"""
    if not design_doc:
        return []
    text = design_doc.lower()
    reasons: List[MatchReason] = []
    seen: set[str] = set()
    # 按 weight 降序，保证 framework(1.3) / domain(1.2) / resilience(1.1) 优先
    sorted_routes = sorted(
        table.routes,
        key=lambda r: float(r.get("weight", 1.0) or 1.0),
        reverse=True,
    )
    for route in sorted_routes:
        skill = route.get("skill")
        if not skill or skill in seen:
            continue
        keywords = [str(k).lower() for k in (route.get("keywords") or [])]
        hit = next((k for k in keywords if k and k in text), None)
        if hit:
            reasons.append(MatchReason(skill=skill, tier="fallback", detail=hit))
            seen.add(skill)
    return reasons


def _tags_to_reasons(
    tech_tags: Dict[str, Any],
    table: _RoutingTable,
) -> List[MatchReason]:
    reasons: List[MatchReason] = []
    seen: set[str] = set()
    rationales = tech_tags.get("rationale") or {}
    if not isinstance(rationales, dict):
        rationales = {}

    for group in ("domains", "capabilities"):
        raw_list = tech_tags.get(group) or []
        if not isinstance(raw_list, list):
            _LOG.warning("tech_tags.%s is not a list; ignored", group)
            continue
        for tag in raw_list:
            if not isinstance(tag, str):
                continue
            tag_norm = tag.strip().lower()
            if not tag_norm:
                continue
            skill = table.by_stem.get(tag_norm)
            if not skill:
                _LOG.warning("unknown tech_tag %r in group %s; skipped", tag, group)
                continue
            if skill in seen:
                continue
            reasons.append(
                MatchReason(
                    skill=skill,
                    tier="tag",
                    detail=tag_norm,
                    rationale=str(rationales.get(tag_norm, "") or rationales.get(tag, "") or ""),
                )
            )
            seen.add(skill)
    return reasons


def _merge_defaults(
    reasons: List[MatchReason],
    table: _RoutingTable,
) -> List[MatchReason]:
    seen = {r.skill for r in reasons}
    merged = list(reasons)
    for skill in table.defaults:
        if skill and skill not in seen:
            merged.append(MatchReason(skill=skill, tier="default", detail="baseline"))
            seen.add(skill)
    return merged


def _sort_by_weight(
    reasons: List[MatchReason],
    table: _RoutingTable,
) -> List[MatchReason]:
    """按 weight 降序稳定排序（framework 1.3 > domain 1.2 > 通用 1.0）。

    权重相同 / 无权重时保持原始 emission 顺序。defaults 本身没有 weight，
    所以排序应该在合并 defaults 之前做，避免 defaults 被权重搅乱其固定垫底位置。
    """
    return sorted(
        reasons,
        key=lambda r: table.weights.get(r.skill, 1.0),
        reverse=True,
    )


def resolve(
    tech_tags: Optional[Dict[str, Any]],
    design_doc: str = "",
    *,
    yaml_path: Optional[Path] = None,
) -> SkillRouting:
    """把 tech_tags（可选）+ design_doc（兜底）映射成 skill 清单。

    - tech_tags 非空且至少命中一条合法 tag → source="tags"
    - tech_tags 空或全部非法 → 退到关键词匹配 → source="fallback"
    - 两路都空 → 仅返回 defaults → source="empty"
    """
    table = load_table(yaml_path)

    reasons: List[MatchReason] = []
    source = "tags"
    if isinstance(tech_tags, dict):
        reasons = _tags_to_reasons(tech_tags, table)

    if not reasons:
        reasons = _match_keywords(design_doc, table)
        source = "fallback" if reasons else "empty"

    # weight 排序：主路径（tags）里 Phase1 可能按思路随意列序，靠 weight 把
    # framework/domain 等高优先级规则排到前面，确保 LLM 最先读硬约束。
    # fallback 路径里 _match_keywords 已经按 weight 排过，这里再排一次是幂等的。
    reasons = _sort_by_weight(reasons, table)
    reasons = _merge_defaults(reasons, table)
    skills = [r.skill for r in reasons]
    return SkillRouting(skills=skills, reasons=reasons, source=source)


def render_for_prompt(routing: SkillRouting) -> str:
    """把 SkillRouting 渲染成注入到 system prompt 顶部的 XML 块。"""
    if not routing or not routing.skills:
        return ""
    lines: List[str] = []
    lines.append("<skill-routing source=\"" + routing.source + "\">")
    lines.append("The LarkFlow engine has pre-resolved the following skill files for this demand.")
    lines.append("You MUST read every listed file with `file_editor` (action: read) before writing any code or review, in the listed order. Do NOT re-run keyword matching yourself — this list IS the authoritative set.")
    lines.append("")
    for r in routing.reasons:
        tail = f"  [{r.tier}: {r.detail}]" if r.detail else f"  [{r.tier}]"
        if r.rationale:
            tail += f"  — {r.rationale}"
        lines.append(f"- {r.skill}{tail}")
    lines.append("</skill-routing>")
    return "\n".join(lines)
