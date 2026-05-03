"""D5 Step 4-5: Review verdict 解析 + 自动回归调度单测。

覆盖：
- _parse_review_verdict: PASS / REGRESS(+findings) / 无标签 / 多种 content 格式
- Step 5 会追加 _try_regress 用例
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline.core.contracts import Stage
from pipeline.core.engine import (
    PHASE_CODING,
    PHASE_REVIEWING,
    _extract_last_assistant_text,
    _parse_review_verdict,
    _try_regress,
)


# ==========================================
# _extract_last_assistant_text
# ==========================================
def test_extract_last_assistant_text_str():
    session = {"messages": [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "hello"},
    ]}
    assert _extract_last_assistant_text(session) == "hello"


def test_extract_last_assistant_text_list_of_dict():
    session = {"messages": [
        {"role": "assistant", "content": [
            {"type": "text", "text": "line1"},
            {"type": "tool_use", "name": "x"},
            {"type": "text", "text": "line2"},
        ]},
    ]}
    txt = _extract_last_assistant_text(session)
    assert "line1" in txt and "line2" in txt


def test_extract_last_assistant_text_reverse_order():
    """应取最后一条 assistant，而不是第一条。"""
    session = {"messages": [
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": "mid"},
        {"role": "assistant", "content": "new"},
    ]}
    assert _extract_last_assistant_text(session) == "new"


def test_extract_last_assistant_text_skips_empty():
    session = {"messages": [
        {"role": "assistant", "content": "real"},
        {"role": "assistant", "content": ""},
    ]}
    assert _extract_last_assistant_text(session) == "real"


def test_extract_last_assistant_text_empty_session():
    assert _extract_last_assistant_text({}) == ""
    assert _extract_last_assistant_text({"messages": []}) == ""


# ==========================================
# _parse_review_verdict
# ==========================================
def test_parse_pass():
    session = {"messages": [
        {"role": "assistant", "content": "## Verdict\nApproved\n\n<review-verdict>PASS</review-verdict>"},
    ]}
    verdict, findings = _parse_review_verdict(session)
    assert verdict == "pass"
    assert findings == ""


def test_parse_regress_with_findings():
    txt = (
        "## Findings\n- [🔴] service/order.go:42 — gorm import\n\n"
        "<review-findings>\n"
        "- service/order.go:42 — remove gorm import; move DB behind biz.OrderRepo.\n"
        "</review-findings>\n"
        "<review-verdict>REGRESS</review-verdict>"
    )
    session = {"messages": [{"role": "assistant", "content": txt}]}
    verdict, findings = _parse_review_verdict(session)
    assert verdict == "regress"
    assert "remove gorm import" in findings
    assert "biz.OrderRepo" in findings


def test_parse_regress_without_findings_still_regress():
    """REGRESS 标签存在但没 findings —— 仍判 regress，findings 为空。下游可降级为通用 hint。"""
    session = {"messages": [{"role": "assistant", "content": "<review-verdict>REGRESS</review-verdict>"}]}
    verdict, findings = _parse_review_verdict(session)
    assert verdict == "regress"
    assert findings == ""


def test_parse_no_tag_defaults_to_pass():
    """保守兜底：Agent 漏写标签 → 按 PASS 处理，不误伤正常流程。"""
    session = {"messages": [{"role": "assistant", "content": "## Verdict\nApproved\n(no tag)"}]}
    verdict, findings = _parse_review_verdict(session)
    assert verdict == "pass"
    assert findings == ""


def test_parse_empty_session_defaults_to_pass():
    assert _parse_review_verdict({}) == ("pass", "")
    assert _parse_review_verdict({"messages": []}) == ("pass", "")


def test_parse_case_insensitive_verdict():
    session = {"messages": [{"role": "assistant", "content": "<review-verdict>regress</review-verdict>"}]}
    verdict, _ = _parse_review_verdict(session)
    assert verdict == "regress"


def test_parse_multiple_tags_uses_last():
    """若文本里同时出现多次 verdict（比如 few-shot 引用）—— 以最末尾为准。"""
    txt = (
        "Example: <review-verdict>PASS</review-verdict>\n"
        "Now actual output:\n"
        "<review-findings>- x — y</review-findings>\n"
        "<review-verdict>REGRESS</review-verdict>"
    )
    session = {"messages": [{"role": "assistant", "content": txt}]}
    verdict, findings = _parse_review_verdict(session)
    assert verdict == "regress"
    assert "x — y" in findings


def test_parse_content_as_block_list():
    """Anthropic 风格 content: list[{type,text}]。"""
    session = {"messages": [
        {"role": "assistant", "content": [
            {"type": "text", "text": "## Verdict\nApproved"},
            {"type": "text", "text": "<review-verdict>PASS</review-verdict>"},
        ]},
    ]}
    verdict, _ = _parse_review_verdict(session)
    assert verdict == "pass"


# ==========================================
# _try_regress —— 核心调度逻辑
# ==========================================
def _make_session_store():
    """内存 session store：_load_session / _save_session 的替身。"""
    store: dict[str, dict] = {}

    def loader(demand_id):
        return store.get(demand_id)

    def saver(demand_id, session):
        store[demand_id] = session

    return store, loader, saver


def _fake_append_user_text(session, text):
    """测试替身：直接 append 到 session['messages']，避免依赖 provider。"""
    session.setdefault("messages", []).append({"role": "user", "content": text})


def test_try_regress_first_attempt_succeeds():
    store, loader, saver = _make_session_store()
    store["d1"] = {"demand_id": "d1", "messages": []}
    logger = MagicMock()

    with patch("pipeline.core.engine._load_session", side_effect=loader), \
         patch("pipeline.core.engine._save_session", side_effect=saver), \
         patch("pipeline.core.engine.append_user_text", side_effect=_fake_append_user_text):
        ok = _try_regress("d1", "- foo.go:1 — do X", logger)

    assert ok is True
    reg = store["d1"]["regression"]
    assert reg["attempts"] == 1
    assert len(reg["history"]) == 1
    assert reg["history"][0]["to"] == "coding"
    # findings 已注入 messages
    msgs = store["d1"]["messages"]
    assert any("自动回归 第 1 次" in str(m) for m in msgs)
    assert any("foo.go:1" in str(m) for m in msgs)
    logger.info.assert_called()


def test_try_regress_counts_up_then_rejects():
    """第 4 次（超过 max_attempts=3）应返回 False。"""
    store, loader, saver = _make_session_store()
    store["d1"] = {"demand_id": "d1", "messages": []}
    logger = MagicMock()

    with patch("pipeline.core.engine._load_session", side_effect=loader), \
         patch("pipeline.core.engine._save_session", side_effect=saver), \
         patch("pipeline.core.engine.append_user_text", side_effect=_fake_append_user_text):
        for i in range(3):
            assert _try_regress("d1", f"findings round {i+1}", logger) is True
        assert store["d1"]["regression"]["attempts"] == 3

        # 第 4 次应被上限拒绝
        assert _try_regress("d1", "findings 4", logger) is False
        # attempts 不应递增
        assert store["d1"]["regression"]["attempts"] == 3
        # 拒绝时应打 regression_exhausted 日志
        events = [
            c.kwargs.get("extra", {}).get("event")
            for c in logger.warning.call_args_list
        ]
        assert "regression_exhausted" in events


def test_try_regress_empty_findings_uses_fallback_hint():
    """REGRESS 但 findings 为空 —— 仍触发回归，注入通用提示。"""
    store, loader, saver = _make_session_store()
    store["d1"] = {"demand_id": "d1", "messages": []}
    logger = MagicMock()

    with patch("pipeline.core.engine._load_session", side_effect=loader), \
         patch("pipeline.core.engine._save_session", side_effect=saver), \
         patch("pipeline.core.engine.append_user_text", side_effect=_fake_append_user_text):
        ok = _try_regress("d1", "", logger)

    assert ok is True
    msgs = store["d1"]["messages"]
    assert any("未提供具体 findings" in str(m) for m in msgs)


def test_try_regress_missing_session_returns_false():
    store, loader, saver = _make_session_store()
    # store 为空，loader 返回 None
    logger = MagicMock()
    with patch("pipeline.core.engine._load_session", side_effect=loader), \
         patch("pipeline.core.engine._save_session", side_effect=saver), \
         patch("pipeline.core.engine.append_user_text", side_effect=_fake_append_user_text):
        assert _try_regress("ghost", "x", logger) is False


def test_end_to_end_regress_then_pass_via_resume_from_phase():
    """端到端 smoke：resume_from_phase 进入 reviewing → REGRESS → 回 coding
    → testing → reviewing → PASS → 进入 deploy_approval（挂起）。

    用 patch 替身 _run_phase / _request_deploy_approval / _load_session 等重依赖。
    """
    from pipeline.core import engine

    call_order: list[str] = []
    verdict_sequence = iter(["regress", "pass"])
    store: dict[str, dict] = {
        "D1": {
            "demand_id": "D1",
            "messages": [],
            "phase": engine.PHASE_REVIEWING,
            "provider": "stub",
        }
    }

    def fake_run_phase(demand_id, phase):
        call_order.append(phase)
        return True  # 全部"完成"，verdict 由下面替身决定

    def fake_advance(demand_id, phase):
        return store[demand_id]

    def fake_parse(session):
        """按 verdict_sequence 决定 reviewing 的结论。"""
        try:
            v = next(verdict_sequence)
        except StopIteration:
            v = "pass"
        return v, "sample findings"

    deploy_requested: list[bool] = []

    def fake_request_deploy_approval(demand_id, logger):
        deploy_requested.append(True)

    with patch.object(engine, "_run_phase", side_effect=fake_run_phase), \
         patch.object(engine, "_advance_to_phase", side_effect=fake_advance), \
         patch.object(engine, "_parse_review_verdict", side_effect=fake_parse), \
         patch.object(engine, "_request_deploy_approval", side_effect=fake_request_deploy_approval), \
         patch.object(engine, "_load_session", side_effect=lambda d: store.get(d)), \
         patch.object(engine, "_save_session", side_effect=lambda d, s: store.__setitem__(d, s)), \
         patch.object(engine, "append_user_text", side_effect=_fake_append_user_text):
        engine.resume_from_phase("D1", engine.PHASE_REVIEWING)

    # reviewing（REGRESS）→ 回 coding → testing → reviewing（PASS）→ deploy_approval
    assert call_order == [
        engine.PHASE_REVIEWING,
        engine.PHASE_CODING,
        engine.PHASE_TESTING,
        engine.PHASE_REVIEWING,
    ]
    assert deploy_requested == [True]
    # regression 计数为 1
    assert store["D1"]["regression"]["attempts"] == 1


def test_end_to_end_regress_exhausted_marks_failed():
    """连续 REGRESS 超过 max_attempts=3 → _mark_failed 被调用，不再推 deploy。"""
    from pipeline.core import engine

    call_order: list[str] = []
    store: dict[str, dict] = {
        "D2": {
            "demand_id": "D2",
            "messages": [],
            "phase": engine.PHASE_REVIEWING,
            "provider": "stub",
        }
    }

    def fake_run_phase(demand_id, phase):
        call_order.append(phase)
        return True

    mark_failed_calls: list[tuple] = []

    def fake_mark_failed(demand_id, phase, error):
        mark_failed_calls.append((demand_id, phase, error))

    with patch.object(engine, "_run_phase", side_effect=fake_run_phase), \
         patch.object(engine, "_advance_to_phase", side_effect=lambda d, p: store[d]), \
         patch.object(engine, "_parse_review_verdict", return_value=("regress", "keep failing")), \
         patch.object(engine, "_request_deploy_approval") as mock_deploy_req, \
         patch.object(engine, "_mark_failed", side_effect=fake_mark_failed), \
         patch.object(engine, "_load_session", side_effect=lambda d: store.get(d)), \
         patch.object(engine, "_save_session", side_effect=lambda d, s: store.__setitem__(d, s)), \
         patch.object(engine, "append_user_text", side_effect=_fake_append_user_text):
        engine.resume_from_phase("D2", engine.PHASE_REVIEWING)

    # 第 1 次 reviewing → regress ⇒ coding/test/reviewing（第 2 次）
    # 第 2 次 reviewing → regress ⇒ coding/test/reviewing（第 3 次）
    # 第 3 次 reviewing → regress ⇒ coding/test/reviewing（第 4 次）
    # 第 4 次 reviewing → regress 但 attempts(3)>=max(3) → mark_failed
    # 故 reviewing 被执行 4 次，coding/testing 各 3 次
    assert call_order.count(engine.PHASE_REVIEWING) == 4
    assert call_order.count(engine.PHASE_CODING) == 3
    assert call_order.count(engine.PHASE_TESTING) == 3
    assert len(mark_failed_calls) == 1
    assert mark_failed_calls[0][1] == engine.PHASE_REVIEWING
    assert "regression exhausted" in mark_failed_calls[0][2]
    mock_deploy_req.assert_not_called()


def test_try_regress_when_policy_disabled_returns_false():
    """若 DAG review.on_failure = None（关闭自动回归），应直接返回 False。"""
    store, loader, saver = _make_session_store()
    store["d1"] = {"demand_id": "d1", "messages": []}
    logger = MagicMock()

    # 构造一个 review 节点 on_failure=None 的 fake DAG
    from pipeline.dag.schema import DAG, DAGNode

    fake_nodes = {
        Stage.DESIGN: DAGNode(stage=Stage.DESIGN, prompt_file="p1"),
        Stage.CODING: DAGNode(stage=Stage.CODING, prompt_file="p2"),
        Stage.TEST: DAGNode(stage=Stage.TEST, prompt_file="p3"),
        Stage.REVIEW: DAGNode(stage=Stage.REVIEW, prompt_file="p4", on_failure=None),
    }
    fake_dag = DAG(name="noop", nodes=fake_nodes, entry=Stage.DESIGN)

    with patch("pipeline.core.engine._load_session", side_effect=loader), \
         patch("pipeline.core.engine._save_session", side_effect=saver), \
         patch("pipeline.core.engine.append_user_text", side_effect=_fake_append_user_text), \
         patch("pipeline.dag.schema.default_dag", return_value=fake_dag):
        ok = _try_regress("d1", "x", logger)
    assert ok is False
    assert "regression" not in store["d1"]
