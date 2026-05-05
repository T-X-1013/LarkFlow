"""feedback 单元测试：解析 <skill-feedback> 块、落盘 jsonl、gap_type 自动分类。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline.skills import feedback as F


_SINGLE_BLOCK = """
## Findings
- [🔴] internal/service/order.go:42 — idempotency in memory

<skill-feedback>
  <category>idempotency</category>
  <severity>critical</severity>
  <summary>Idempotency must be backed by shared storage.</summary>
  <evidence>internal/service/order.go:42 — `var seen = map[string]bool{}`</evidence>
  <suggested-skill>skills/governance/idempotency.md</suggested-skill>
  <gap-type>content</gap-type>
  <injected-skills>skills/framework/kratos.md, skills/governance/idempotency.md</injected-skills>
</skill-feedback>

<review-verdict>PASS</review-verdict>
"""

_TWO_BLOCKS_ONE_MALFORMED = """
<skill-feedback>
  <category>rate_limit</category>
  <severity>high</severity>
  <summary>Per-identity rate limit missing on /register.</summary>
  <evidence>internal/service/user.go:11</evidence>
  <suggested-skill>skills/governance/rate_limit.md</suggested-skill>
</skill-feedback>

noise noise noise

<skill-feedback>
  <category>logging</category>
  no proper children here
</skill-feedback>

<skill-feedback>
  <category>auth</category>
  <severity>medium</severity>
  <summary>JWT alg not pinned.</summary>
  <evidence>internal/server/http.go:22</evidence>
  <suggested-skill>skills/governance/auth.md</suggested-skill>
</skill-feedback>
"""


def test_parse_single_block_with_all_fields():
    rows = F.parse_feedback_blocks(_SINGLE_BLOCK)
    assert len(rows) == 1
    r = rows[0]
    assert r["category"] == "idempotency"
    assert r["severity"] == "critical"
    assert r["suggested_skill"] == "skills/governance/idempotency.md"
    assert r["gap_type"] == "content"
    assert "skills/governance/idempotency.md" in r["injected_skills"]


def test_parse_multiple_blocks_skips_empty():
    rows = F.parse_feedback_blocks(_TWO_BLOCKS_ONE_MALFORMED)
    # 中间那块只有 <category>，其他 _FIELDS 都空 → 仍然保留（有 category）
    # 但我们的过滤逻辑：只要任一字段非空就保留。这里第二块 category=logging → 保留。
    assert len(rows) == 3
    cats = [r["category"] for r in rows]
    assert cats == ["rate_limit", "logging", "auth"]


def test_parse_returns_empty_on_empty_input():
    assert F.parse_feedback_blocks("") == []
    assert F.parse_feedback_blocks("no blocks here at all") == []


def test_classify_gap_routing_when_suggested_not_in_injected():
    gap = F._classify_gap(
        suggested_skill="skills/governance/idempotency.md",
        injected_skills=["skills/framework/kratos.md"],
    )
    assert gap == "routing"


def test_classify_gap_content_when_injected():
    gap = F._classify_gap(
        suggested_skill="skills/governance/idempotency.md",
        injected_skills=["skills/governance/idempotency.md", "skills/framework/kratos.md"],
    )
    assert gap == "content"


def test_classify_gap_respects_agent_declared():
    gap = F._classify_gap(
        suggested_skill="skills/x.md",
        injected_skills=[],  # 按注入判断会是 routing
        agent_declared="content",  # 显式声明优先
    )
    assert gap == "content"


def test_capture_feedback_writes_two_jsonl(tmp_path, monkeypatch):
    # 切 cwd，让 tmp/ 和 telemetry/ 落到 tmp_path
    monkeypatch.chdir(tmp_path)
    demand_id = "D123"
    rows = F.capture_feedback(
        demand_id,
        _SINGLE_BLOCK,
        injected_skills=["skills/framework/kratos.md"],  # 故意不包含 suggested，测试 routing 分类兜底
    )
    assert len(rows) == 1
    # agent 显式声明 content → 优先；注入逻辑上是 routing 但被 agent 覆盖
    assert rows[0]["gap_type"] == "content"

    per_demand = tmp_path / "tmp" / demand_id / "skill_feedback.jsonl"
    global_log = tmp_path / "telemetry" / "skill_feedback.jsonl"
    assert per_demand.exists() and global_log.exists()

    d_line = json.loads(per_demand.read_text(encoding="utf-8").strip())
    g_line = json.loads(global_log.read_text(encoding="utf-8").strip())
    assert d_line["demand_id"] == "D123"
    assert d_line["suggested_skill"] == "skills/governance/idempotency.md"
    assert g_line["injected_skills"] == ["skills/framework/kratos.md"]


def test_capture_feedback_falls_back_to_auto_classify(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = """
<skill-feedback>
  <category>rate_limit</category>
  <severity>high</severity>
  <summary>no per-ip throttle</summary>
  <evidence>x.go:1</evidence>
  <suggested-skill>skills/governance/rate_limit.md</suggested-skill>
</skill-feedback>
"""
    rows = F.capture_feedback("D1", text, injected_skills=["skills/framework/kratos.md"])
    assert rows and rows[0]["gap_type"] == "routing"  # 未注入 → routing


def test_capture_feedback_no_blocks_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = F.capture_feedback("D1", "no feedback blocks here", injected_skills=[])
    assert rows == []
    # 没有块就不该写文件
    assert not (tmp_path / "telemetry" / "skill_feedback.jsonl").exists()
