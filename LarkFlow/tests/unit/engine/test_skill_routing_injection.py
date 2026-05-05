"""Engine 集成：Phase1 tech_tags → session["skill_routing"] → Phase2/4 system prompt 注入。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from pipeline.core import engine
from pipeline.skills import resolver as R


@pytest.fixture
def routing_yaml(tmp_path: Path, monkeypatch) -> Path:
    data = {
        "routes": [
            {"keywords": ["用户", "register"], "skill": "skills/domain/user.md", "weight": 1.2},
            {"keywords": ["幂等", "idempotency"], "skill": "skills/governance/idempotency.md", "weight": 1.0},
        ],
        "defaults": ["skills/framework/kratos.md"],
    }
    p = tmp_path / "skill-routing.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    # 让 resolver 在任何默认路径调用时也用这份测试 YAML
    monkeypatch.setattr(R, "_DEFAULT_YAML_PATH", p)
    return p


def test_augment_injects_block_when_routing_present(temp_session_store, routing_yaml, monkeypatch):
    # 造一个带 skill_routing 的 session
    routing = R.resolve({"domains": ["user"], "capabilities": ["idempotency"]}, "", yaml_path=routing_yaml)
    session = {
        "demand_id": "D42",
        "messages": [],
        "skill_routing": routing.to_dict(),
    }
    temp_session_store.save("D42", session)

    prompt = "# Role: Senior Go Engineer\n..."
    out = engine._augment_with_skill_routing("D42", prompt)
    assert out.startswith("<skill-routing")
    assert "skills/domain/user.md" in out
    assert "skills/governance/idempotency.md" in out
    assert "skills/framework/kratos.md" in out
    assert "# Role: Senior Go Engineer" in out


def test_augment_passthrough_when_no_routing(temp_session_store):
    temp_session_store.save("D0", {"demand_id": "D0", "messages": []})
    prompt = "unchanged"
    assert engine._augment_with_skill_routing("D0", prompt) == prompt


def test_augment_passthrough_when_session_missing(temp_session_store):
    # D999 不存在 → 直接返回原 prompt，不抛
    assert engine._augment_with_skill_routing("D999", "x") == "x"


def test_harvest_skill_feedback_writes_jsonl(temp_session_store, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    review_text = """
## Findings
- [🔴] x.go:1 — something

<skill-feedback>
  <category>auth</category>
  <severity>critical</severity>
  <summary>JWT alg not pinned</summary>
  <evidence>x.go:1</evidence>
  <suggested-skill>skills/governance/auth.md</suggested-skill>
  <gap-type>content</gap-type>
  <injected-skills>skills/governance/auth.md</injected-skills>
</skill-feedback>

<review-verdict>PASS</review-verdict>
"""
    session = {
        "demand_id": "D7",
        "messages": [{"role": "assistant", "content": review_text}],
        "skill_routing": {"skills": ["skills/governance/auth.md"], "reasons": [], "source": "tags"},
    }
    temp_session_store.save("D7", session)

    engine._harvest_skill_feedback("D7")

    assert (tmp_path / "tmp" / "D7" / "skill_feedback.jsonl").exists()
    assert (tmp_path / "telemetry" / "skill_feedback.jsonl").exists()


def test_harvest_skill_feedback_noop_on_no_blocks(temp_session_store, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session = {
        "demand_id": "D8",
        "messages": [{"role": "assistant", "content": "plain PASS, no feedback"}],
    }
    temp_session_store.save("D8", session)

    engine._harvest_skill_feedback("D8")  # 不抛
    assert not (tmp_path / "telemetry" / "skill_feedback.jsonl").exists()


def test_pending_approval_preserves_tech_tags_on_save_and_resolve(routing_yaml):
    """模拟 ask_human_approval 拦截路径存的 tech_tags 最终能被 resolver 正确消费。"""
    pending = {
        "tool_call_id": "tc1",
        "tool_name": "ask_human_approval",
        "summary": "add nickname",
        "design_doc": "涉及用户和幂等",
        "tech_tags": {"domains": ["user"], "capabilities": ["idempotency"]},
    }
    routing = R.resolve(
        pending.get("tech_tags"),
        pending.get("design_doc", ""),
        yaml_path=routing_yaml,
    )
    assert routing.source == "tags"
    assert "skills/domain/user.md" in routing.skills
    assert "skills/governance/idempotency.md" in routing.skills


def test_ask_human_approval_resolves_and_logs_before_suspend(routing_yaml, monkeypatch):
    """核心语义：Phase1 调 ask_human_approval 的瞬间就 resolve + 写 session["skill_routing"] + 打日志，
    不等审批通过。这样挂起期间 log 和 session 都能看到本次路由。"""
    from unittest.mock import MagicMock, patch

    logger = MagicMock()
    session = {"logger": logger, "phase": "design", "pending_approval": None}

    turn = MagicMock()
    turn.usage = {}
    turn.finished = False
    turn.text_blocks = []
    tool_call = MagicMock()
    tool_call.id = "tc-1"
    tool_call.name = "ask_human_approval"
    tool_call.arguments = {
        "summary": "add nickname",
        "design_doc": "涉及用户和幂等",
        "tech_tags": {"domains": ["user"], "capabilities": ["idempotency"]},
    }
    turn.tool_calls = [tool_call]

    with patch.object(engine, "_load_session", return_value=session), \
         patch.object(engine, "_save_session"), \
         patch.object(engine, "_create_turn_with_retry", return_value=turn), \
         patch.object(engine, "_prepare_tech_doc", return_value=("tok", "url")), \
         patch.object(engine, "send_lark_card"), \
         patch("pipeline.config.lark.chat_id", return_value="ou_x"):
        completed = engine.run_agent_loop("D-EARLY", "sys prompt")

    assert completed is False
    # 立即写入 session["skill_routing"]，不等审批
    assert session.get("skill_routing") is not None
    assert "skills/domain/user.md" in session["skill_routing"]["skills"]
    assert "skills/governance/idempotency.md" in session["skill_routing"]["skills"]
    assert session["skill_routing"]["source"] == "tags"
    # pending_approval 同步保留 tech_tags
    assert session["pending_approval"]["tech_tags"] == {
        "domains": ["user"],
        "capabilities": ["idempotency"],
    }
    # 日志事件
    events = [c.kwargs.get("extra", {}).get("event") for c in logger.info.call_args_list]
    assert "skill_routing_resolved" in events


def test_ask_human_approval_without_tech_tags_falls_back_to_keywords(routing_yaml):
    """Agent 忘填 tech_tags 时，提前 resolve 应退到关键词匹配，不空跑。"""
    from unittest.mock import MagicMock, patch

    logger = MagicMock()
    session = {"logger": logger, "phase": "design", "pending_approval": None}

    turn = MagicMock()
    turn.usage = {}
    turn.finished = False
    turn.text_blocks = []
    tool_call = MagicMock()
    tool_call.id = "tc-2"
    tool_call.name = "ask_human_approval"
    tool_call.arguments = {
        "summary": "s",
        "design_doc": "需求涉及用户登录",
        # 故意不填 tech_tags
    }
    turn.tool_calls = [tool_call]

    with patch.object(engine, "_load_session", return_value=session), \
         patch.object(engine, "_save_session"), \
         patch.object(engine, "_create_turn_with_retry", return_value=turn), \
         patch.object(engine, "_prepare_tech_doc", return_value=("tok", "url")), \
         patch.object(engine, "send_lark_card"), \
         patch("pipeline.config.lark.chat_id", return_value="ou_x"):
        engine.run_agent_loop("D-FALLBACK", "sys prompt")

    assert session["skill_routing"]["source"] == "fallback"
    assert "skills/domain/user.md" in session["skill_routing"]["skills"]
