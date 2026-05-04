"""确定性 skill router：把需求文本映射为本次必读的 skill 清单。

三层策略与 `rules/skill-routing.yaml` 的 schema 对齐：

1. baseline  : 任何 Go 服务改动都无条件注入的基线 skill。
2. conditional: trigger 命中即必读，不受 top-K 截断。
3. routes    : keyword 子串匹配 + weight 排序，取 top-K（默认 5）。

Agent 不再自己读 YAML；router 结果通过 session["skill_routing"] 传给 Phase1/2/4，
并在 system prompt 中作为权威清单注入。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import yaml


_LOG = logging.getLogger("larkflow.skill_router")

# 路由 YAML 默认路径：<workspace_root>/rules/skill-routing.yaml
# workspace_root 即 LarkFlow/ 目录本身
_DEFAULT_YAML_PATH = (
    Path(__file__).resolve().parents[2] / "rules" / "skill-routing.yaml"
)

DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class MatchReason:
    """单条 skill 被选中的理由，便于 prompt 注入与审计回溯。"""

    skill: str
    tier: str              # "baseline" | "conditional" | "route"
    detail: str            # baseline 的 reason / 触发的关键词 / 匹配的 keywords
    score: float = 0.0     # conditional 固定 1.0；route 用 weight
    source: str = ""       # Tier-2 专属："keyword" | "semantic" | "both"；其他层为空


@dataclass
class SkillRouting:
    """router 的最终产物，写入 session["skill_routing"]。"""

    skills: list[str] = field(default_factory=list)
    reasons: list[MatchReason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为纯 dict，便于 JSON 持久化与 REST 返回。"""
        return {
            "skills": list(self.skills),
            "reasons": [
                {
                    "skill": r.skill,
                    "tier": r.tier,
                    "detail": r.detail,
                    "score": r.score,
                    "source": r.source,
                }
                for r in self.reasons
            ],
        }

    def render_prompt_block(self) -> str:
        """把清单渲染成可直接拼进 system_prompt 的 Markdown 段落。"""
        if not self.skills:
            return ""
        lines: list[str] = [
            "## Skill Routing (authoritative)",
            "",
            (
                "以下 skill 清单由 `pipeline/skills/router.py` 按 "
                "`rules/skill-routing.yaml` 规则计算得出，是本次必读的权威清单。"
                "不要再自行解析 YAML 或增删 skill。"
            ),
            "",
        ]
        reason_by_skill: dict[str, MatchReason] = {}
        for reason in self.reasons:
            # 同一 skill 可能被多层同时触发，保留 tier 优先级最高的那一条
            prev = reason_by_skill.get(reason.skill)
            if prev is None or _tier_rank(reason.tier) < _tier_rank(prev.tier):
                reason_by_skill[reason.skill] = reason
        for skill in self.skills:
            reason = reason_by_skill.get(skill)
            if reason is None:
                lines.append(f"- `{skill}`")
                continue
            lines.append(
                f"- `{skill}` — [{reason.tier}] {reason.detail}"
            )
        lines.append("")
        return "\n".join(lines)


def _tier_rank(tier: str) -> int:
    """tier 的展示优先级：baseline > conditional > route。"""
    return {"baseline": 0, "conditional": 1, "route": 2}.get(tier, 9)


def load_routing_table(
    path: Optional[Path] = None,
) -> dict[str, Any]:
    """读取并解析 skill-routing.yaml。

    独立函数是为了方便单测注入自定义 YAML 路径与缓存失效。

    @params:
        path: YAML 文件路径；None 时使用项目内默认路径。

    @return:
        解析后的 dict，至少包含 baseline/conditional/routes 三个键（可为空列表）。
    """
    yaml_path = path or _DEFAULT_YAML_PATH
    with yaml_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("baseline", [])
    data.setdefault("conditional", [])
    data.setdefault("routes", [])
    return data


def route_from_text(
    text: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    table: Optional[dict[str, Any]] = None,
    semantic_hits: Optional[dict[str, float]] = None,
) -> SkillRouting:
    """对一段自然语言需求执行三层路由。

    @params:
        text          : 需求原文（自然语言或已规范化的描述文本都可）。
        top_k         : Tier-2 routes 层保留的最大条目数。
        table         : 预加载的路由表；None 时按默认路径读取。
        semantic_hits : 预计算的语义召回结果 `{skill: score}`；
                        None 时按 env 开关自动决定是否调 embedding 通道。
                        传空 dict 表示显式禁用语义通道。

    @return:
        SkillRouting：最终 skills 列表（已去重、按 tier 与 weight 排序）+ 原因。
    """
    routing_table = table if table is not None else load_routing_table()
    normalized = (text or "").lower()

    if semantic_hits is None:
        semantic_hits = _resolve_semantic_hits(text, routing_table)

    baseline_reasons = _collect_baseline(routing_table.get("baseline", []))
    conditional_reasons = _collect_conditional(
        routing_table.get("conditional", []), normalized
    )
    route_reasons = _collect_routes(
        routing_table.get("routes", []),
        normalized,
        top_k=top_k,
        semantic_hits=semantic_hits,
    )

    ordered_skills: list[str] = []
    seen: set[str] = set()
    for reason in (*baseline_reasons, *conditional_reasons, *route_reasons):
        if reason.skill in seen:
            continue
        seen.add(reason.skill)
        ordered_skills.append(reason.skill)

    return SkillRouting(
        skills=ordered_skills,
        reasons=[*baseline_reasons, *conditional_reasons, *route_reasons],
    )


def _collect_baseline(items: Sequence[dict[str, Any]]) -> list[MatchReason]:
    """Tier-0：无条件注入。"""
    result: list[MatchReason] = []
    for item in items:
        skill = item.get("skill")
        if not skill:
            continue
        result.append(
            MatchReason(
                skill=str(skill),
                tier="baseline",
                detail=str(item.get("reason", "") or "无条件必读"),
                score=1.0,
            )
        )
    return result


def _collect_conditional(
    items: Sequence[dict[str, Any]],
    normalized_text: str,
) -> list[MatchReason]:
    """Tier-1：trigger.keywords_any 命中即必读，不做截断。"""
    result: list[MatchReason] = []
    for item in items:
        skill = item.get("skill")
        trigger = item.get("trigger") or {}
        keywords_any = trigger.get("keywords_any") or []
        if not skill or not keywords_any:
            continue
        matched = _first_matching_keyword(normalized_text, keywords_any)
        if not matched:
            continue
        reason_text = item.get("reason", "") or ""
        detail = (
            f"触发关键词「{matched}」：{reason_text}"
            if reason_text
            else f"触发关键词「{matched}」"
        )
        result.append(
            MatchReason(
                skill=str(skill),
                tier="conditional",
                detail=detail,
                score=1.0,
            )
        )
    return result


def _collect_routes(
    items: Sequence[dict[str, Any]],
    normalized_text: str,
    *,
    top_k: int,
    semantic_hits: Optional[dict[str, float]] = None,
) -> list[MatchReason]:
    """Tier-2：keyword ∪ semantic 双通道召回 → 按 weight DESC 取 top-K。

    排序键：
        1. weight DESC （业务 skill weight=1.2 优于 generic=1.0）
        2. 命中信号强度 DESC（keyword 命中数 + semantic 分数，tie-break）
        3. 路由在 YAML 中的原始顺序（稳定排序兜底）

    source 标记：
        - 只命中关键词  → "keyword"
        - 只命中语义    → "semantic"
        - 两者都命中    → "both"
    """
    semantic_hits = semantic_hits or {}
    scored: list[tuple[float, float, int, MatchReason]] = []
    for idx, item in enumerate(items):
        skill = item.get("skill")
        keywords = item.get("keywords") or []
        if not skill:
            continue
        skill_str = str(skill)
        matched_keywords = [kw for kw in keywords if _contains(normalized_text, kw)]
        sem_score = float(semantic_hits.get(skill_str, 0.0))
        keyword_hit = bool(matched_keywords)
        semantic_hit = sem_score > 0.0
        if not keyword_hit and not semantic_hit:
            continue
        if keyword_hit and semantic_hit:
            source = "both"
        elif keyword_hit:
            source = "keyword"
        else:
            source = "semantic"
        detail_parts: list[str] = []
        if keyword_hit:
            head = ", ".join(str(kw) for kw in matched_keywords[:5])
            extra = (
                f"（共 {len(matched_keywords)} 条）"
                if len(matched_keywords) > 5
                else ""
            )
            detail_parts.append(f"命中关键词：{head}{extra}")
        if semantic_hit:
            detail_parts.append(f"语义相似度 {sem_score:.2f}")
        detail = "；".join(detail_parts)
        weight = float(item.get("weight", 1.0))
        # 命中信号强度：关键词数权重 1.0 + 语义分数权重 1.0（取 [0,1] 范围）
        strength = float(len(matched_keywords)) + sem_score
        reason = MatchReason(
            skill=skill_str,
            tier="route",
            detail=detail,
            score=weight,
            source=source,
        )
        scored.append((-weight, -strength, idx, reason))

    scored.sort()
    return [reason for _, _, _, reason in scored[: max(0, top_k)]]


def _resolve_semantic_hits(
    text: str,
    table: dict[str, Any],
) -> dict[str, float]:
    """按 env 开关决定是否调语义通道；失败安全地返回空 dict。"""
    from pipeline.skills import semantic  # 局部导入，避免模块加载时就拉 openai SDK
    if not semantic.is_enabled():
        return {}
    try:
        return semantic.semantic_match(text, table=table)
    except Exception as exc:  # 任何异常都降级到纯关键词
        _LOG.warning("semantic router failed, falling back to keyword only: %s", exc)
        return {}


def _contains(normalized_text: str, keyword: Any) -> bool:
    """大小写无关子串匹配。

    keyword 可能是 int（YAML 里裸写的 429）、bool 等非字符串类型，
    统一转成小写字符串再比较；空值视为不匹配。
    """
    if keyword is None or keyword == "":
        return False
    return str(keyword).lower() in normalized_text


def _first_matching_keyword(
    normalized_text: str, keywords: Iterable[str]
) -> Optional[str]:
    """返回第一个命中的关键词，没命中返回 None。"""
    for kw in keywords:
        if _contains(normalized_text, kw):
            return str(kw)
    return None
