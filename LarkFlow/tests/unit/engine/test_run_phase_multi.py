"""D7 Step 3: `_run_phase_multi` 并行执行器单测。

全部 LLM / prompt / client 行为都被 mock；本测试只验证并行编排与持久化语义。

覆盖：
- `_run_phase` 在 phase=REVIEWING 且 review 节点并行时，自动 dispatch 到 `_run_phase_multi`
- 非并行模板 / 非 review 阶段走单 agent 路径不受影响
- 三路 role reviewer 都成功 → 合并 metrics + by_role + 仲裁 agent 调用
- 一路 worker 抛异常 → 其他两路仍完成，aggregator 拿到 status=failed
- 子 session 结束后 phase 为 done，list_active 不包含子 key
- parent session["review_multi"]["subroles"] 记录每路 status / tokens / duration
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

from pipeline import engine
from pipeline.contracts import Stage
from pipeline.dag.schema import DAGNode
from pipeline.persistence import SqliteSessionStore
from pipeline.subsession import load_subsession, subsession_key


def _make_parent_session(demand_id: str) -> Dict[str, Any]:
    return {
        "demand_id": demand_id,
        "provider": "openai",
        "target_dir": "/tmp/demo",
        "workspace_root": "/tmp",
        "phase": engine.PHASE_TESTING,
        "history": [],
        "provider_state": {"messages": []},
        "metrics": {"tokens_input": 500, "tokens_output": 250},
        "session_mode": "messages",
    }


def _make_parallel_node(workers: int = 3) -> DAGNode:
    return DAGNode(
        stage=Stage.REVIEW,
        prompt_files={
            "security": "phase4_review_security.md",
            "testing-coverage": "phase4_review_testing.md",
            "kratos-layering": "phase4_review_kratos.md",
        },
        aggregator_prompt_file="phase4_aggregator.md",
        parallel_workers=workers,
    )


class RunPhaseMultiTestCase(unittest.TestCase):
    """用真实 SqliteSessionStore（tmp 目录）+ mock LLM 跑整个 multi review 流程。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="larkflow-multi-")
        self._db = str(Path(self._tmp.name) / "sessions.db")
        self._store = SqliteSessionStore(self._db)
        self._orig_store = engine.STORE
        engine.STORE = self._store  # monkey-patch 模块级 STORE

        # 把工件目录也挪到临时位置
        self._orig_cwd = Path.cwd()
        self._workdir = tempfile.TemporaryDirectory(prefix="larkflow-multi-work-")
        import os
        os.chdir(self._workdir.name)

    def tearDown(self):
        import os
        os.chdir(self._orig_cwd)
        engine.STORE = self._orig_store
        self._tmp.cleanup()
        self._workdir.cleanup()

    def _seed_parent(self, demand_id: str) -> None:
        self._store.save(demand_id, _make_parent_session(demand_id))

    def test_single_agent_path_for_non_parallel_review(self):
        """review 节点 is_parallel=False 时 `_run_phase` 走原单 agent 逻辑。"""
        demand_id = "D_single"
        self._seed_parent(demand_id)

        with patch.object(engine, "_resolve_review_node_for_demand", return_value=DAGNode(
            stage=Stage.REVIEW, prompt_file="phase4_review.md"
        )), patch.object(engine, "run_agent_loop", return_value=True) as run_mock, \
             patch.object(engine, "load_prompt", return_value="prompt"), \
             patch.object(engine, "trace_phase_execution") as trace_mock:
            trace_mock.return_value.__enter__ = lambda s: MagicMock()
            trace_mock.return_value.__exit__ = lambda s, *a: None
            ok = engine._run_phase(demand_id, engine.PHASE_REVIEWING)

        self.assertTrue(ok)
        run_mock.assert_called_once_with(demand_id, "prompt")

    def test_all_three_roles_succeed_then_aggregator_runs(self):
        """三路都成功 → aggregator 被调用 → 主 session tokens 合并正确。"""
        demand_id = "D_ok"
        self._seed_parent(demand_id)
        node = _make_parallel_node()

        call_order: list = []
        lock = threading.Lock()

        def fake_run_agent_loop(did: str, system_prompt: str) -> bool:
            with lock:
                call_order.append(did)
            # 子 session 分支：设置 tokens + 追加 assistant history
            session = self._store.get(did)
            if session is None:
                return False
            if "::review::" in did:
                role = did.split("::review::")[1]
                token_in = {"security": 100, "testing-coverage": 200, "kratos-layering": 150}[role]
                token_out = {"security": 40, "testing-coverage": 70, "kratos-layering": 60}[role]
                session["metrics"] = {"tokens_input": token_in, "tokens_output": token_out}
                session["history"].append({
                    "role": "assistant",
                    "content": f"[{role}] review done. <review-verdict>PASS</review-verdict>",
                })
            else:
                # 主 session（aggregator）：追加最终 verdict
                session["history"].append({
                    "role": "assistant",
                    "content": "<review-verdict>PASS</review-verdict>",
                })
            self._store.save(did, session)
            return True

        with patch.object(engine, "run_agent_loop", side_effect=fake_run_agent_loop), \
             patch.object(engine, "build_client", return_value=MagicMock()), \
             patch.object(engine, "initialize_session", return_value={
                 "history": [], "provider_state": {"messages": []}, "session_mode": "messages"
             }), \
             patch.object(engine, "load_prompt", return_value="prompt"), \
             patch.object(engine, "trace_phase_execution") as trace_mock:
            trace_mock.return_value.__enter__ = lambda s: MagicMock()
            trace_mock.return_value.__exit__ = lambda s, *a: None
            ok = engine._run_phase_multi(demand_id, node)

        self.assertTrue(ok)
        # 4 次调用：三路 worker + 一次 aggregator
        self.assertEqual(len(call_order), 4)
        # 主 session 的 tokens 合并（初值 500/250 + 三路 450/170 = 950/420）
        parent = self._store.get(demand_id)
        self.assertEqual(parent["metrics"]["tokens_input"], 500 + 100 + 200 + 150)
        self.assertEqual(parent["metrics"]["tokens_output"], 250 + 40 + 70 + 60)
        # by_role 三条并列
        by_role = parent["metrics"]["by_role"]
        self.assertEqual(set(by_role.keys()), {"security", "testing-coverage", "kratos-layering"})
        self.assertEqual(by_role["testing-coverage"]["tokens_input"], 200)
        # review_multi.subroles 记录三路
        subroles = parent["review_multi"]["subroles"]
        self.assertEqual(len(subroles), 3)
        self.assertTrue(all(r["status"] == "done" for r in subroles))
        # 子 session 被标记 done（list_active 不含）
        active = set(self._store.list_active())
        for role in ("security", "testing-coverage", "kratos-layering"):
            self.assertNotIn(subsession_key(demand_id, role), active)

    def test_one_role_crashes_others_still_complete(self):
        """一路 worker 内部抛异常 → 返回 status=failed；另两路正常；aggregator 照跑。"""
        demand_id = "D_crash"
        self._seed_parent(demand_id)
        node = _make_parallel_node()

        def fake_run_agent_loop(did: str, system_prompt: str) -> bool:
            if "::review::security" in did:
                raise RuntimeError("boom in security reviewer")
            session = self._store.get(did)
            if session is None:
                return False
            if "::review::" in did:
                session["metrics"] = {"tokens_input": 50, "tokens_output": 20}
                session["history"].append({
                    "role": "assistant",
                    "content": "<review-verdict>PASS</review-verdict>",
                })
            else:
                session["history"].append({
                    "role": "assistant",
                    "content": "<review-verdict>REGRESS</review-verdict>",
                })
            self._store.save(did, session)
            return True

        with patch.object(engine, "run_agent_loop", side_effect=fake_run_agent_loop), \
             patch.object(engine, "build_client", return_value=MagicMock()), \
             patch.object(engine, "initialize_session", return_value={
                 "history": [], "provider_state": {"messages": []}, "session_mode": "messages"
             }), \
             patch.object(engine, "load_prompt", return_value="prompt"), \
             patch.object(engine, "trace_phase_execution") as trace_mock:
            trace_mock.return_value.__enter__ = lambda s: MagicMock()
            trace_mock.return_value.__exit__ = lambda s, *a: None
            ok = engine._run_phase_multi(demand_id, node)

        self.assertTrue(ok)  # aggregator 本身成功调用
        parent = self._store.get(demand_id)
        subroles = {r["role"]: r for r in parent["review_multi"]["subroles"]}
        self.assertEqual(subroles["security"]["status"], "failed")
        self.assertIn("boom", subroles["security"]["error"])
        self.assertEqual(subroles["testing-coverage"]["status"], "done")
        self.assertEqual(subroles["kratos-layering"]["status"], "done")

    def test_dispatch_in_run_phase(self):
        """`_run_phase(PHASE_REVIEWING)` 看到 parallel 节点时应调 `_run_phase_multi`。"""
        demand_id = "D_dispatch"
        self._seed_parent(demand_id)
        node = _make_parallel_node()

        with patch.object(engine, "_resolve_review_node_for_demand", return_value=node), \
             patch.object(engine, "_run_phase_multi", return_value=True) as multi_mock:
            ok = engine._run_phase(demand_id, engine.PHASE_REVIEWING)

        self.assertTrue(ok)
        multi_mock.assert_called_once_with(demand_id, node)

    def test_non_reviewing_phase_never_dispatches_multi(self):
        """Phase != REVIEWING 时绝不走并行路径。"""
        demand_id = "D_other"
        self._seed_parent(demand_id)

        with patch.object(engine, "_run_phase_multi") as multi_mock, \
             patch.object(engine, "run_agent_loop", return_value=True), \
             patch.object(engine, "load_prompt", return_value="prompt"), \
             patch.object(engine, "trace_phase_execution") as trace_mock:
            trace_mock.return_value.__enter__ = lambda s: MagicMock()
            trace_mock.return_value.__exit__ = lambda s, *a: None
            engine._run_phase(demand_id, engine.PHASE_CODING)

        multi_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
