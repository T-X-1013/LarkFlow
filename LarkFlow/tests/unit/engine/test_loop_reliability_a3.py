"""A3 Loop 可靠性单元测试：超时 / 重试 / 最大轮数 / 空响应退出"""
import concurrent.futures
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.core import engine
from pipeline.llm.adapter import AgentTurn, ToolCall
from pipeline.core.persistence import SqliteSessionStore


def _make_turn(tool_calls=None, finished=False, text=None):
    return AgentTurn(
        text_blocks=[text] if text else [],
        tool_calls=tool_calls or [],
        finished=finished,
        raw_response=None,
        usage={},
    )


class LoopReliabilityA3TestCase(unittest.TestCase):
    def setUp(self):
        self._db_tmp = tempfile.TemporaryDirectory(prefix="larkflow-a3-")
        self._orig_store = engine.STORE
        engine.STORE = SqliteSessionStore(str(Path(self._db_tmp.name) / "s.db"))

        self._build_client_patch = patch.object(engine, "build_client", return_value=object())
        self._build_client_patch.start()

        self.demand_id = "DEMAND-A3"
        engine.STORE.save(self.demand_id, {
            "provider": "openai",
            "history": [],
            "pending_approval": None,
            "provider_state": {},
            "phase": engine.PHASE_CODING,
        })

        # 保证每个用例都有独立的环境变量
        for k in ("AGENT_TURN_TIMEOUT", "AGENT_MAX_RETRIES", "AGENT_MAX_TURNS", "AGENT_MAX_EMPTY_STREAK"):
            os.environ.pop(k, None)

    def tearDown(self):
        self._build_client_patch.stop()
        engine.STORE = self._orig_store
        self._db_tmp.cleanup()
        for k in ("AGENT_TURN_TIMEOUT", "AGENT_MAX_RETRIES", "AGENT_MAX_TURNS", "AGENT_MAX_EMPTY_STREAK"):
            os.environ.pop(k, None)

    # --- 超轮数保护 -----------------------------------------------------

    def test_exceeding_max_turns_raises(self):
        os.environ["AGENT_MAX_TURNS"] = "3"

        # 永远返回未完成的非空 turn，让循环耗尽轮数
        turn = _make_turn(text="thinking...")
        with patch.object(engine, "_create_turn_with_retry", return_value=turn):
            with self.assertRaises(RuntimeError) as ctx:
                engine.run_agent_loop(self.demand_id, "sys")
        self.assertIn("AGENT_MAX_TURNS", str(ctx.exception))

    # --- 空响应退出 -----------------------------------------------------

    def test_consecutive_empty_turns_raise(self):
        os.environ["AGENT_MAX_EMPTY_STREAK"] = "2"

        # 真空 turn：无 tool_calls / 未 finished / 无文本
        empty = _make_turn()
        with patch.object(engine, "_create_turn_with_retry", return_value=empty):
            with self.assertRaises(RuntimeError) as ctx:
                engine.run_agent_loop(self.demand_id, "sys")
        self.assertIn("empty turns", str(ctx.exception))

    def test_empty_streak_resets_on_productive_turn(self):
        """中间出现一次有文本的 turn 应重置空响应计数"""
        os.environ["AGENT_MAX_EMPTY_STREAK"] = "3"

        turns = [
            _make_turn(),                # empty streak=1
            _make_turn(),                # empty streak=2
            _make_turn(text="hi"),       # reset -> 0
            _make_turn(),                # streak=1
            _make_turn(text="done", finished=True),
        ]
        it = iter(turns)
        with patch.object(engine, "_create_turn_with_retry", side_effect=lambda *a, **kw: next(it)):
            completed = engine.run_agent_loop(self.demand_id, "sys")
        self.assertTrue(completed)

    # --- 超时 ------------------------------------------------------------

    def test_create_turn_timeout_triggers_retry(self):
        os.environ["AGENT_TURN_TIMEOUT"] = "1"
        os.environ["AGENT_MAX_RETRIES"] = "2"

        call_count = {"n": 0}

        def slow_then_fast(session, system_prompt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                time.sleep(3)  # 触发超时
            return _make_turn(finished=True, text="ok")

        # 不 mock sleep：time.sleep 与 engine.time.sleep 是同一对象，patch 会影响 slow_then_fast
        # 这里接受约 3s 的测试耗时（1s 超时 + 1s~2s 退避 + 第一批线程 shutdown 等待）
        with patch.object(engine, "create_turn", side_effect=slow_then_fast):
            session = engine._load_session(self.demand_id)
            turn = engine._create_turn_with_retry(session, "sys", session["logger"], "coding")

        self.assertTrue(turn.finished)
        self.assertGreaterEqual(call_count["n"], 2)

    # --- 指数退避重试 ---------------------------------------------------

    def test_generic_exception_is_retried_until_max(self):
        os.environ["AGENT_MAX_RETRIES"] = "3"

        def always_fail(session, system_prompt):
            raise RuntimeError("api boom")

        with patch.object(engine, "create_turn", side_effect=always_fail), \
             patch.object(engine.time, "sleep", lambda *a: None):
            session = engine._load_session(self.demand_id)
            with self.assertRaises(RuntimeError) as ctx:
                engine._create_turn_with_retry(session, "sys", session["logger"], "coding")
        self.assertIn("api boom", str(ctx.exception))

    def test_retry_recovers_from_transient_error(self):
        os.environ["AGENT_MAX_RETRIES"] = "3"

        count = {"n": 0}

        def flaky(session, system_prompt):
            count["n"] += 1
            if count["n"] == 1:
                raise RuntimeError("transient")
            return _make_turn(finished=True, text="ok")

        with patch.object(engine, "create_turn", side_effect=flaky), \
             patch.object(engine.time, "sleep", lambda *a: None):
            session = engine._load_session(self.demand_id)
            turn = engine._create_turn_with_retry(session, "sys", session["logger"], "coding")
        self.assertTrue(turn.finished)
        self.assertEqual(count["n"], 2)

    # --- run_agent_loop 层异常 → _run_phase 置 failed -------------------

    def test_run_phase_marks_failed_on_max_turns(self):
        os.environ["AGENT_MAX_TURNS"] = "2"
        turn = _make_turn(text="busy")
        with patch.object(engine, "_create_turn_with_retry", return_value=turn):
            ok = engine._run_phase(self.demand_id, engine.PHASE_CODING)

        self.assertFalse(ok)
        final = engine.STORE.get(self.demand_id)
        self.assertEqual(final["phase"], engine.PHASE_FAILED)
        self.assertIn("AGENT_MAX_TURNS", final["last_error"]["message"])


if __name__ == "__main__":
    unittest.main()
