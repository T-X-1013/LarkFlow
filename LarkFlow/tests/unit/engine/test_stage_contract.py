"""D4 Step 9: StageResult 契约落盘单测。

覆盖：
- _run_phase 出场分发：success / pending_approval / exception
- _record_stage_result 对 deploying 等契约外 phase 自动短路
- resume_after_approval: approved=True 补记 Design SUCCESS；approved=False 记 REJECTED
- build_state 从 session["stage_results"] 反序列化，对损坏/缺失数据兜底
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from pipeline import engine, engine_control
from pipeline.contracts import Stage, StageStatus


# ==========================================
# _run_phase 分发
# ==========================================
def _ctx_noop():
    """返回一个做 __enter__/__exit__ no-op 的 MagicMock，用来替身 trace_phase_execution。"""
    ctx = MagicMock()
    ctx.__enter__ = lambda self: MagicMock()
    ctx.__exit__ = lambda self, *a: None
    return ctx


def test_run_phase_success_records_stage_result(temp_session_store, stub_build_client):
    temp_session_store.save(
        "D1",
        {
            "demand_id": "D1",
            "provider": "openai",
            "target_dir": "/tmp/demo",
            "phase": "design",
            "metrics": {"tokens_input": 100, "tokens_output": 50},
        },
    )

    def fake_run(demand_id, _prompt):
        s = engine._load_session(demand_id)
        s["metrics"]["tokens_input"] += 300
        s["metrics"]["tokens_output"] += 200
        engine._save_session(demand_id, s)
        time.sleep(0.01)
        return True

    with patch.object(engine, "run_agent_loop", side_effect=fake_run), patch.object(
        engine, "load_prompt", return_value="sys"
    ), patch.object(engine, "check_lifecycle"), patch.object(
        engine, "trace_phase_execution", return_value=_ctx_noop()
    ):
        assert engine._run_phase("D1", engine.PHASE_DESIGN) is True

    sr = engine._load_session("D1")["stage_results"]["design"]
    assert sr["status"] == "success"
    assert sr["tokens"] == {"input": 300, "output": 200}
    assert sr["duration_ms"] >= 10
    assert sr["errors"] == []


def test_run_phase_pending_does_not_record(temp_session_store, stub_build_client):
    temp_session_store.save(
        "D2",
        {
            "demand_id": "D2",
            "provider": "openai",
            "target_dir": "/tmp/demo",
            "phase": "coding",
            "metrics": {"tokens_input": 0, "tokens_output": 0},
        },
    )

    def fake_run(demand_id, _prompt):
        s = engine._load_session(demand_id)
        s["pending_approval"] = {"tool_call_id": "c", "tool_name": "ask_human_approval"}
        engine._save_session(demand_id, s)
        return False

    with patch.object(engine, "run_agent_loop", side_effect=fake_run), patch.object(
        engine, "load_prompt", return_value="sys"
    ), patch.object(engine, "check_lifecycle"), patch.object(
        engine, "trace_phase_execution", return_value=_ctx_noop()
    ):
        assert engine._run_phase("D2", engine.PHASE_CODING) is False

    s = engine._load_session("D2")
    assert "coding" not in (s.get("stage_results") or {})


def test_run_phase_exception_records_failed(temp_session_store, stub_build_client):
    temp_session_store.save(
        "D3",
        {
            "demand_id": "D3",
            "provider": "openai",
            "target_dir": "/tmp/demo",
            "phase": "testing",
            "metrics": {"tokens_input": 5, "tokens_output": 3},
        },
    )

    def boom(demand_id, _prompt):
        s = engine._load_session(demand_id)
        s["metrics"]["tokens_input"] += 50
        engine._save_session(demand_id, s)
        raise RuntimeError("kaboom")

    with patch.object(engine, "run_agent_loop", side_effect=boom), patch.object(
        engine, "load_prompt", return_value="sys"
    ), patch.object(engine, "check_lifecycle"), patch.object(
        engine, "trace_phase_execution", return_value=_ctx_noop()
    ), patch.object(engine, "send_lark_text"):
        assert engine._run_phase("D3", engine.PHASE_TESTING) is False

    s = engine._load_session("D3")
    sr = s["stage_results"]["test"]  # testing → test 在契约层
    assert sr["status"] == "failed"
    assert sr["errors"] == ["kaboom"]
    assert sr["tokens"]["input"] == 50
    assert s["phase"] == "failed"
    assert s["last_error"]["phase"] == "testing"


# ==========================================
# _record_stage_result 契约外短路
# ==========================================
def test_record_stage_result_skips_non_contract_phase(temp_session_store, stub_build_client):
    temp_session_store.save(
        "D4",
        {"demand_id": "D4", "provider": "openai", "phase": "deploying", "metrics": {}},
    )
    engine._record_stage_result("D4", "deploying", StageStatus.SUCCESS)
    s = engine._load_session("D4")
    assert "deploying" not in (s.get("stage_results") or {})


# ==========================================
# resume_after_approval
# ==========================================
def _seed_pending_design(store, did):
    store.save(
        did,
        {
            "demand_id": did,
            "provider": "openai",
            "target_dir": "/tmp/demo",
            "phase": "design_pending",
            "metrics": {"tokens_input": 1000, "tokens_output": 500},
            "pending_approval": {
                "tool_call_id": "c1",
                "tool_name": "ask_human_approval",
                "summary": "s",
                "design_doc": "d",
            },
            "messages": [],
            "history": [],
            "_stage_start": {"design": {"ts": time.time() - 2, "tokens_in": 0, "tokens_out": 0}},
        },
    )


def test_resume_approved_records_design_success(temp_session_store, stub_build_client):
    _seed_pending_design(temp_session_store, "DA")
    engine_control.register("需求 A", demand_id="DA")

    with patch.object(engine, "resume_from_phase") as m_next, patch.object(
        engine, "append_tool_result"
    ), patch.object(engine, "trace_approval_resume", return_value=_ctx_noop()):
        engine.resume_after_approval("DA", approved=True, feedback="ok")

    sr = engine._load_session("DA")["stage_results"]["design"]
    assert sr["status"] == "success"
    assert sr["tokens"]["input"] == 1000
    assert sr["duration_ms"] > 0
    assert m_next.called


def test_resume_rejected_records_design_rejected(temp_session_store, stub_build_client):
    _seed_pending_design(temp_session_store, "DR")
    engine_control.register("需求 R", demand_id="DR")

    with patch.object(engine, "_run_phase") as m_run, patch.object(
        engine, "append_tool_result"
    ), patch.object(engine, "trace_approval_resume", return_value=_ctx_noop()):
        engine.resume_after_approval("DR", approved=False, feedback="需求不清")

    sr = engine._load_session("DR")["stage_results"]["design"]
    assert sr["status"] == "rejected"
    assert sr["errors"] == ["需求不清"]
    assert m_run.called  # 驳回后重跑 Design


# ==========================================
# build_state 反射
# ==========================================
def test_build_state_hydrates_stage_results(temp_session_store):
    ctl = engine_control.register("X", demand_id="BS1")
    temp_session_store.save(
        "BS1",
        {
            "demand_id": "BS1",
            "phase": "coding",
            "stage_results": {
                "design": {
                    "stage": "design",
                    "status": "success",
                    "artifact_path": "https://x.y/doc",
                    "tokens": {"input": 500, "output": 300},
                    "duration_ms": 12000,
                    "errors": [],
                },
                "coding": {
                    "stage": "coding",
                    "status": "pending",
                    "artifact_path": "/tmp/tgt",
                    "tokens": {"input": 0, "output": 0},
                    "duration_ms": 0,
                    "errors": [],
                },
            },
        },
    )
    state = engine_control.build_state(ctl, temp_session_store.get("BS1"))
    assert state.current_stage == Stage.CODING
    assert state.stages[Stage.DESIGN].status == StageStatus.SUCCESS
    assert state.stages[Stage.DESIGN].tokens.input == 500
    assert state.stages[Stage.DESIGN].artifact_path == "https://x.y/doc"
    assert state.stages[Stage.CODING].status == StageStatus.PENDING


def test_build_state_tolerates_bad_data(temp_session_store):
    ctl = engine_control.register("X", demand_id="BS2")
    temp_session_store.save(
        "BS2",
        {
            "demand_id": "BS2",
            "phase": "design",
            "stage_results": {"bogus": {"x": 1}, "design": {"broken": True}},
        },
    )
    state = engine_control.build_state(ctl, temp_session_store.get("BS2"))
    assert state.stages == {}


def test_build_state_missing_stage_results_ok(temp_session_store):
    ctl = engine_control.register("X", demand_id="BS3")
    temp_session_store.save("BS3", {"demand_id": "BS3", "phase": "design"})
    state = engine_control.build_state(ctl, temp_session_store.get("BS3"))
    assert state.stages == {}
