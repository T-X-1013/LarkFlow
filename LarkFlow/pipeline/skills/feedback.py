"""解析 Phase4 最终消息里的 <skill-feedback> XML 块，落盘到 per-demand + 全局 jsonl。

输入来源：Phase4 review agent 按 rules/skill-feedback-loop.md 产出的 XML 块
输出：
  - tmp/<demand_id>/skill_feedback.jsonl  — per-demand 审计
  - telemetry/skill_feedback.jsonl        — 全局追加，供 digest 脚本消费

输出行字段（每块一行 JSON）：
  demand_id / ts / category / severity / summary / evidence / suggested_skill
  gap_type              — "routing" | "content" | "unknown"
  injected_skills       — Phase2/4 当时被注入的 skill 列表（来自 session["skill_routing"]）
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOG = logging.getLogger("larkflow.skill_feedback")

_BLOCK_RE = re.compile(r"<skill-feedback>(.*?)</skill-feedback>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<(?P<name>[a-zA-Z_-]+)>(?P<body>.*?)</(?P=name)>", re.DOTALL)

_FIELDS = (
    "category",
    "severity",
    "summary",
    "evidence",
    "suggested-skill",
    "gap-type",
    "injected-skills",
)


def parse_feedback_blocks(text: str) -> List[Dict[str, str]]:
    """容错解析：接受块外有任意 markdown 噪声；块内缺字段置空串。"""
    if not text:
        return []
    results: List[Dict[str, str]] = []
    for m in _BLOCK_RE.finditer(text):
        body = m.group(1)
        # 收集所有一级子 tag；多次出现取最后一次
        fields: Dict[str, str] = {}
        for tm in _TAG_RE.finditer(body):
            name = tm.group("name").strip().lower()
            fields[name] = tm.group("body").strip()
        # 规范字段名：suggested-skill → suggested_skill 等
        normalized = {k.replace("-", "_"): fields.get(k, "") for k in _FIELDS}
        # 过滤空壳（全部字段为空）
        if any(normalized.values()):
            results.append(normalized)
    return results


def _classify_gap(
    suggested_skill: str,
    injected_skills: Iterable[str],
    agent_declared: str = "",
) -> str:
    """agent 已经在块里显式声明 <gap-type> 时优先用它；否则按注入情况兜底判断。"""
    decl = (agent_declared or "").strip().lower()
    if decl in ("routing", "content"):
        return decl
    if not suggested_skill:
        return "unknown"
    injected_set = {s for s in injected_skills if s}
    if suggested_skill in injected_set:
        return "content"
    return "routing"


def _demand_log_path(demand_id: str) -> Path:
    return Path("tmp") / str(demand_id) / "skill_feedback.jsonl"


def _global_log_path() -> Path:
    return Path("telemetry") / "skill_feedback.jsonl"


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def capture_feedback(
    demand_id: str,
    final_message: str,
    injected_skills: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """从 Phase4 final message 里抽块，落盘两份，并返回规范化记录。

    非致命：任何异常都被记日志吞掉，不影响 pipeline 主流程。
    """
    injected_list = list(injected_skills or [])
    rows: List[Dict[str, Any]] = []
    try:
        blocks = parse_feedback_blocks(final_message or "")
    except Exception as exc:
        _LOG.warning("parse skill-feedback failed: %s", exc, exc_info=True)
        return rows

    if not blocks:
        return rows

    now = time.time()
    for b in blocks:
        suggested_skill = b.get("suggested_skill", "")
        gap_type = _classify_gap(
            suggested_skill=suggested_skill,
            injected_skills=injected_list,
            agent_declared=b.get("gap_type", ""),
        )
        row = {
            "demand_id": str(demand_id),
            "ts": now,
            "category": b.get("category", ""),
            "severity": b.get("severity", ""),
            "summary": b.get("summary", ""),
            "evidence": b.get("evidence", ""),
            "suggested_skill": suggested_skill,
            "gap_type": gap_type,
            "injected_skills": injected_list,
        }
        rows.append(row)

    try:
        for r in rows:
            _append_jsonl(_demand_log_path(demand_id), r)
            _append_jsonl(_global_log_path(), r)
    except OSError as exc:
        _LOG.warning("write skill_feedback jsonl failed: %s", exc, exc_info=True)
    return rows
