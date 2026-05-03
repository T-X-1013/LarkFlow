"""A6 引擎端到端集成测试：串起 A1~A5 验证关键流程"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.core import engine
from pipeline.ops.deploy_strategy import DeployOutcome, DeployStrategy, register
from pipeline.llm.adapter import AgentTurn, ToolCall
from pipeline.core.persistence import SqliteSessionStore


def _turn(tool_calls=None, finished=False, text=None):
    return AgentTurn(
        text_blocks=[text] if text else [],
        tool_calls=tool_calls or [],
        finished=finished,
        raw_response=None,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "latency_ms": 100},
    )


# --- start_new_demand: 挂起到 design_pending ---------------------------

def test_start_new_demand_suspends_on_approval(temp_session_store, stub_build_client, monkeypatch, tmp_path):
    """Phase 1 调用 ask_human_approval → phase=design_pending + pending_approval 已写入"""
    # scaffold 替身，避免真实 copytree
    monkeypatch.setattr(engine, "_ensure_target_scaffold", lambda *a, **kw: None)
    monkeypatch.setattr(engine, "get_provider_name", lambda: "openai")
    monkeypatch.setattr(engine, "initialize_session", lambda provider, text, client: {
        "provider": provider, "history": [{"role": "user", "content": text}],
        "pending_approval": None, "provider_state": {},
    })

    approval_turn = _turn(tool_calls=[ToolCall(
        id="call-1", name="ask_human_approval",
        arguments={"summary": "s1", "design_doc": "doc1"},
    )])
    monkeypatch.setattr(engine, "_create_turn_with_retry",
                        lambda *a, **kw: approval_turn)
    # 不真的发飞书
    monkeypatch.delenv("LARK_CHAT_ID", raising=False)
    monkeypatch.delenv("LARK_WEBHOOK_URL", raising=False)
    # load_prompt 真实路径依赖 agents/，给个 no-op
    monkeypatch.setattr(engine, "load_prompt", lambda name: "SYS")

    engine.start_new_demand("DEMAND-E2E-1", "加一个 age 字段")

    saved = temp_session_store.get("DEMAND-E2E-1")
    assert saved["phase"] == engine.PHASE_DESIGN_PENDING
    assert saved["pending_approval"]["summary"] == "s1"


# --- resume_after_approval: 同意后链式跑到 done -------------------------

def test_resume_after_approval_approved_runs_to_done(temp_session_store, stub_build_client, monkeypatch):
    """同意审批 -> coding/testing/reviewing/deploying/done 全链路"""
    # 预置已挂起的 session
    temp_session_store.save("D-OK", {
        "provider": "openai", "history": [], "provider_state": {},
        "phase": engine.PHASE_DESIGN_PENDING,
        "pending_approval": {
            "tool_call_id": "tc-approval", "tool_name": "ask_human_approval",
            "summary": "s", "design_doc": "d",
        },
    })

    visited = []
    monkeypatch.setattr(engine, "_run_phase",
                        lambda demand_id, phase: visited.append(phase) or True)

    class OkStrategy(DeployStrategy):
        name = "ok-strat"
        def deploy(self, target_dir, logger):
            visited.append("deploy")
            return DeployOutcome(success=True, access_url="http://ok")

    register(OkStrategy())
    temp_session_store.save("D-OK", {
        **temp_session_store.get("D-OK"),
        "deploy_strategy": "ok-strat",
    })

    engine.resume_after_approval("D-OK", approved=True, feedback="lgtm")

    assert visited == [engine.PHASE_CODING, engine.PHASE_TESTING, engine.PHASE_REVIEWING, "deploy"]
    final = temp_session_store.get("D-OK")
    assert final["phase"] == engine.PHASE_DONE
    assert final["pending_approval"] is None


# --- resume_after_approval: 驳回回到 design ----------------------------

def test_resume_after_approval_rejected_goes_back_to_design(temp_session_store, stub_build_client, monkeypatch):
    temp_session_store.save("D-REJ", {
        "provider": "openai", "history": [], "provider_state": {},
        "phase": engine.PHASE_DESIGN_PENDING,
        "pending_approval": {
            "tool_call_id": "tc-1", "tool_name": "ask_human_approval",
            "summary": "", "design_doc": "",
        },
    })

    called = []

    def fake_run_phase(demand_id, phase):
        called.append(phase)
        return True  # design 完成 but no approval re-requested in this test

    monkeypatch.setattr(engine, "_run_phase", fake_run_phase)

    engine.resume_after_approval("D-REJ", approved=False, feedback="需要改")
    final = temp_session_store.get("D-REJ")
    # 驳回后 phase 先置 design，然后 _run_phase 被调用；我们 mock 返回 True 不改 phase
    assert final["phase"] == engine.PHASE_DESIGN
    assert called == [engine.PHASE_DESIGN]


# --- 没有 pending_approval 时 resume 应当无副作用 -----------------------

def test_resume_after_approval_without_pending_is_noop(temp_session_store, stub_build_client, monkeypatch):
    temp_session_store.save("D-NOOP", {
        "provider": "openai", "history": [], "provider_state": {},
        "phase": engine.PHASE_CODING, "pending_approval": None,
    })
    monkeypatch.setattr(engine, "_run_phase", lambda *a: pytest.fail("不应触发"))

    engine.resume_after_approval("D-NOOP", approved=True, feedback="x")


# --- 进程重启恢复：不同 STORE 实例读到持久化的 session ----------------

def test_process_restart_recovers_session(monkeypatch):
    """A1 验收核心场景：save 到磁盘 → 新 STORE 实例可读回 → resume_from_phase 能继续"""
    with tempfile.TemporaryDirectory(prefix="larkflow-restart-") as tmp:
        db_path = str(Path(tmp) / "persist.db")

        # "进程 1" 写入
        store1 = SqliteSessionStore(db_path)
        store1.save("D-RESTART", {
            "provider": "openai", "history": [], "provider_state": {},
            "phase": engine.PHASE_TESTING, "pending_approval": None,
            "target_dir": "/tmp/demo",
        })
        del store1

        # "进程 2" 冷启动：新 STORE 实例 + engine.STORE 指向它
        store2 = SqliteSessionStore(db_path)
        monkeypatch.setattr(engine, "STORE", store2)
        monkeypatch.setattr(engine, "build_client", lambda p: object())

        active = store2.list_active()
        assert "D-RESTART" in active

        # 从 testing 续跑
        visited = []
        monkeypatch.setattr(engine, "_run_phase",
                            lambda demand_id, phase: visited.append(phase) or True)

        class NoopStrategy(DeployStrategy):
            name = "noop"
            def deploy(self, target_dir, logger):
                visited.append("deploy")
                return DeployOutcome(success=True)
        register(NoopStrategy())
        cur = store2.get("D-RESTART")
        cur["deploy_strategy"] = "noop"
        store2.save("D-RESTART", cur)

        engine.resume_from_phase("D-RESTART", engine.PHASE_TESTING)
        assert visited == [engine.PHASE_TESTING, engine.PHASE_REVIEWING, "deploy"]
        assert store2.get("D-RESTART")["phase"] == engine.PHASE_DONE


# --- deploy_app 异常被 resume_from_phase 捕获置 failed -----------------

def test_resume_from_phase_catches_deploy_exception(temp_session_store, stub_build_client, monkeypatch):
    temp_session_store.save("D-CRASH", {
        "provider": "openai", "history": [], "provider_state": {},
        "phase": engine.PHASE_REVIEWING,
    })
    monkeypatch.setattr(engine, "_run_phase", lambda demand_id, phase: True)
    monkeypatch.setattr(engine, "deploy_app",
                        lambda demand_id: (_ for _ in ()).throw(RuntimeError("docker daemon down")))

    engine.resume_from_phase("D-CRASH", engine.PHASE_REVIEWING)
    final = temp_session_store.get("D-CRASH")
    assert final["phase"] == engine.PHASE_FAILED
    assert "docker daemon down" in final["last_error"]["message"]


# --- run_agent_loop 中途持久化：工具执行后 session 已落盘 --------------

def test_run_agent_loop_persists_after_each_turn(temp_session_store, stub_build_client, monkeypatch, tmp_path):
    """A1 + A3 协作：每轮工具执行完都 save 一次，crash-restart 不丢 history"""
    target_dir = tmp_path
    temp_session_store.save("D-MID", {
        "provider": "openai", "history": [], "provider_state": {},
        "phase": engine.PHASE_CODING, "target_dir": str(target_dir),
    })

    turns = iter([
        _turn(tool_calls=[ToolCall(id="t1", name="file_editor",
                                   arguments={"action": "write",
                                              "path": str(target_dir / "a.txt"),
                                              "content": "hi"})]),
        _turn(finished=True, text="done"),
    ])
    monkeypatch.setattr(engine, "_create_turn_with_retry", lambda *a, **kw: next(turns))
    # mock 掉真实 tool 执行，直接返回 ok 字符串
    monkeypatch.setattr(engine, "execute_local_tool", lambda name, args, ctx: "ok")

    engine.run_agent_loop("D-MID", "SYS")

    saved = temp_session_store.get("D-MID")
    # 工具结果应已计入 history（append_tool_result 内部追加）
    assert any("ok" in str(h.get("content", "")) for h in saved["history"])
    # metrics 累加
    assert saved["metrics"]["turns"] >= 2
