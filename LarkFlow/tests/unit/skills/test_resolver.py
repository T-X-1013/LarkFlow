"""resolver 单元测试：合法/非法/空 tags、回退关键词匹配、defaults 合并。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pipeline.skills import resolver as R


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "routing.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    """与生产 rules/skill-routing.yaml 结构对齐：kratos 在 defaults、业务域 1.2、通用 1.0。"""
    return _write_yaml(
        tmp_path,
        {
            "routes": [
                {"keywords": ["用户", "register", "登录"], "skill": "skills/domain/user.md", "weight": 1.2},
                {"keywords": ["订单", "下单"], "skill": "skills/domain/order.md", "weight": 1.2},
                {"keywords": ["rpc"], "skill": "skills/transport/rpc.md", "weight": 1.1},
                {"keywords": ["幂等", "idempotency", "重复提交"], "skill": "skills/governance/idempotency.md", "weight": 1.0},
                {"keywords": ["限流", "rate limit"], "skill": "skills/governance/rate_limit.md", "weight": 1.0},
                {"keywords": ["mysql", "database", "数据库"], "skill": "skills/infra/database.md", "weight": 1.0},
                {"keywords": ["日志", "logging"], "skill": "skills/governance/logging.md", "weight": 1.0},
                {"keywords": ["http"], "skill": "skills/transport/http.md", "weight": 1.0},
            ],
            "defaults": [
                "skills/framework/kratos.md",
                "skills/lang/error.md",
            ],
        },
    )


def test_resolve_with_valid_tags(sample_yaml):
    tags = {
        "domains": ["user"],
        "capabilities": ["idempotency", "database"],
        "rationale": {"idempotency": "防重复提交"},
    }
    routing = R.resolve(tags, design_doc="irrelevant body", yaml_path=sample_yaml)
    assert routing.source == "tags"
    # tag 命中 + defaults 合并
    assert "skills/domain/user.md" in routing.skills
    assert "skills/governance/idempotency.md" in routing.skills
    assert "skills/infra/database.md" in routing.skills
    # defaults 始终合并
    assert "skills/framework/kratos.md" in routing.skills
    assert "skills/lang/error.md" in routing.skills
    # rationale 透传
    reasons_by_skill = {r.skill: r for r in routing.reasons}
    assert reasons_by_skill["skills/governance/idempotency.md"].rationale == "防重复提交"
    assert reasons_by_skill["skills/governance/idempotency.md"].tier == "tag"
    # defaults 标 tier=default
    assert reasons_by_skill["skills/framework/kratos.md"].tier == "default"


def test_resolve_drops_unknown_tag_and_keeps_valid(sample_yaml, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(R._LOG, "warning", lambda msg, *args, **kwargs: warnings.append(msg % args if args else msg))
    tags = {"domains": ["user", "nope_unknown"], "capabilities": []}
    routing = R.resolve(tags, "", yaml_path=sample_yaml)
    assert routing.source == "tags"
    assert "skills/domain/user.md" in routing.skills
    # nope_unknown 没有对应 skill
    assert not any("nope_unknown" in (r.detail or "") for r in routing.reasons)
    # 未知 tag 应触发 WARN
    assert any("unknown tech_tag" in w for w in warnings)


def test_fallback_to_keyword_match_when_no_valid_tag(sample_yaml):
    routing = R.resolve(None, "该需求涉及下单和幂等问题", yaml_path=sample_yaml)
    assert routing.source == "fallback"
    assert "skills/domain/order.md" in routing.skills
    assert "skills/governance/idempotency.md" in routing.skills


def test_fallback_when_tags_all_invalid(sample_yaml):
    # 全部非法 tag → 会退到关键词匹配
    routing = R.resolve(
        {"domains": ["x"], "capabilities": ["y"]},
        "需求涉及用户登录",
        yaml_path=sample_yaml,
    )
    assert routing.source == "fallback"
    assert "skills/domain/user.md" in routing.skills


def test_empty_everything_returns_only_defaults(sample_yaml):
    routing = R.resolve(None, "", yaml_path=sample_yaml)
    assert routing.source == "empty"
    assert routing.skills == [
        "skills/framework/kratos.md",
        "skills/lang/error.md",
    ]


def test_render_block_contains_all_skills_and_rationale(sample_yaml):
    tags = {"domains": ["user"], "rationale": {"user": "会员注册"}}
    routing = R.resolve(tags, "", yaml_path=sample_yaml)
    block = R.render_for_prompt(routing)
    assert "<skill-routing" in block and "</skill-routing>" in block
    assert "skills/domain/user.md" in block
    assert "会员注册" in block
    # defaults 也应该在
    assert "skills/framework/kratos.md" in block


def test_render_empty_routing_returns_empty_string():
    empty = R.SkillRouting(skills=[], reasons=[], source="empty")
    assert R.render_for_prompt(empty) == ""


def test_routing_roundtrip_via_to_from_dict(sample_yaml):
    tags = {"domains": ["user"], "capabilities": ["database"]}
    routing = R.resolve(tags, "", yaml_path=sample_yaml)
    data = routing.to_dict()
    revived = R.SkillRouting.from_dict(data)
    assert revived is not None
    assert revived.skills == routing.skills
    assert revived.source == routing.source
    assert [r.skill for r in revived.reasons] == [r.skill for r in routing.reasons]


def test_tag_path_sorts_by_weight_before_defaults(sample_yaml):
    # Phase1 故意按"想到啥写啥"乱序列标签：logging(1.0) → user(1.2) → rpc(1.1)
    tags = {"capabilities": ["logging", "rpc", "http"], "domains": ["user"]}
    routing = R.resolve(tags, "", yaml_path=sample_yaml)
    # 主路径排序后：user(1.2) → rpc(1.1) → logging(1.0) → http(1.0)
    # defaults（kratos / error）垫底，保持 YAML 列出顺序
    assert routing.skills == [
        "skills/domain/user.md",
        "skills/transport/rpc.md",
        "skills/governance/logging.md",
        "skills/transport/http.md",
        "skills/framework/kratos.md",
        "skills/lang/error.md",
    ]


def test_same_weight_preserves_emission_order(sample_yaml):
    # logging 和 http 都是 1.0，都在 tags 里
    tags = {"capabilities": ["logging", "http"]}
    routing = R.resolve(tags, "", yaml_path=sample_yaml)
    # 同权重下稳定保持 emission 顺序
    assert routing.skills.index("skills/governance/logging.md") < routing.skills.index(
        "skills/transport/http.md"
    )


def test_fallback_path_weight_sorted(sample_yaml):
    # design_doc 同时触发 user(1.2) 和 logging(1.0)；fallback 路径应 user 在前
    routing = R.resolve(None, "需求涉及用户登录和日志", yaml_path=sample_yaml)
    assert routing.source == "fallback"
    assert routing.skills.index("skills/domain/user.md") < routing.skills.index(
        "skills/governance/logging.md"
    )


def test_valid_tags_lists_all_stems(sample_yaml):
    tags = R.valid_tags(R.load_table(sample_yaml))
    assert "user" in tags and "idempotency" in tags
    assert tags == sorted(tags)
