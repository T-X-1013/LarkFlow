"""A2 阶段状态机单元测试"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import engine
from pipeline.persistence import SqliteSessionStore


class StateMachineA2TestCase(unittest.TestCase):
    def setUp(self):
        self._db_tmp = tempfile.TemporaryDirectory(prefix="larkflow-a2-")
        self._orig_store = engine.STORE
        engine.STORE = SqliteSessionStore(str(Path(self._db_tmp.name) / "s.db"))

        self._build_client_patch = patch.object(engine, "build_client", return_value=object())
        self._build_client_patch.start()

        self.demand_id = "DEMAND-A2"
        # 预置一个处于 coding 之前、审批已同意的 session
        engine.STORE.save(self.demand_id, {
            "provider": "openai",
            "history": [],
            "pending_approval": None,
            "provider_state": {},
            "phase": engine.PHASE_DESIGN,
        })

    def tearDown(self):
        self._build_client_patch.stop()
        engine.STORE = self._orig_store
        self._db_tmp.cleanup()

    # --- resume_from_phase 合法性 ----------------------------------------

    def test_resume_from_phase_rejects_invalid_phase(self):
        with self.assertRaises(ValueError):
            engine.resume_from_phase(self.demand_id, "not_a_phase")

    def test_resume_from_phase_rejects_design(self):
        """design / design_pending / done / failed 都不是合法的 resume 入口"""
        with self.assertRaises(ValueError):
            engine.resume_from_phase(self.demand_id, engine.PHASE_DESIGN)

    # --- 链式推进：happy path --------------------------------------------

    def test_resume_from_coding_chains_through_done(self):
        """coding 全链路成功 → testing → reviewing → deploying → done"""
        call_order = []

        def fake_run_phase(demand_id, phase):
            call_order.append(phase)
            return True

        def fake_deploy(demand_id):
            call_order.append("deploy")
            return True

        with patch.object(engine, "_run_phase", side_effect=fake_run_phase), \
             patch.object(engine, "deploy_app", side_effect=fake_deploy):
            engine.resume_from_phase(self.demand_id, engine.PHASE_CODING)

        self.assertEqual(
            call_order,
            [engine.PHASE_CODING, engine.PHASE_TESTING, engine.PHASE_REVIEWING, "deploy"],
        )
        final = engine.STORE.get(self.demand_id)
        self.assertEqual(final["phase"], engine.PHASE_DONE)

    # --- 中途挂起不应推进到下一阶段 --------------------------------------

    def test_suspended_in_coding_does_not_advance(self):
        """coding 挂起（返回 False）→ 不应再调用 testing"""
        call_order = []

        def fake_run_phase(demand_id, phase):
            call_order.append(phase)
            return False  # 挂起

        with patch.object(engine, "_run_phase", side_effect=fake_run_phase), \
             patch.object(engine, "deploy_app") as mock_deploy:
            engine.resume_from_phase(self.demand_id, engine.PHASE_CODING)

        self.assertEqual(call_order, [engine.PHASE_CODING])
        mock_deploy.assert_not_called()

    # --- 断点续跑：从中途阶段恢复 ---------------------------------------

    def test_resume_from_reviewing_skips_earlier_phases(self):
        """从 reviewing 恢复 → 跳过 coding / testing"""
        call_order = []

        def fake_run_phase(demand_id, phase):
            call_order.append(phase)
            return True

        def fake_deploy(demand_id):
            call_order.append("deploy")
            return True

        with patch.object(engine, "_run_phase", side_effect=fake_run_phase), \
             patch.object(engine, "deploy_app", side_effect=fake_deploy):
            engine.resume_from_phase(self.demand_id, engine.PHASE_REVIEWING)

        self.assertEqual(call_order, [engine.PHASE_REVIEWING, "deploy"])

    # --- 部署失败置 failed ----------------------------------------------

    def test_deploy_failure_marks_failed(self):
        def fake_run_phase(demand_id, phase):
            return True

        with patch.object(engine, "_run_phase", side_effect=fake_run_phase), \
             patch.object(engine, "deploy_app", return_value=False):
            engine.resume_from_phase(self.demand_id, engine.PHASE_REVIEWING)

        final = engine.STORE.get(self.demand_id)
        self.assertEqual(final["phase"], engine.PHASE_FAILED)
        self.assertEqual(final["last_error"]["phase"], engine.PHASE_DEPLOYING)

    # --- 阶段异常置 failed ----------------------------------------------

    def test_phase_exception_marks_failed(self):
        """_run_phase 内部 LLM 抛异常 → 置 failed，不向外抛"""
        # 模拟 run_agent_loop 抛异常
        with patch.object(engine, "run_agent_loop", side_effect=RuntimeError("llm boom")):
            ok = engine._run_phase(self.demand_id, engine.PHASE_CODING)

        self.assertFalse(ok)
        final = engine.STORE.get(self.demand_id)
        self.assertEqual(final["phase"], engine.PHASE_FAILED)
        self.assertEqual(final["last_error"]["phase"], engine.PHASE_CODING)
        self.assertIn("llm boom", final["last_error"]["message"])

    # --- kickoff 文本注入 ------------------------------------------------

    def test_advance_to_testing_injects_kickoff(self):
        session = engine._advance_to_phase(self.demand_id, engine.PHASE_TESTING)
        self.assertEqual(session["phase"], engine.PHASE_TESTING)
        # testing 有 kickoff 文本
        self.assertTrue(any(
            "编写测试用例" in (h.get("content") or "") for h in session["history"]
        ))

    def test_advance_to_coding_no_kickoff(self):
        """coding 的 kickoff 由审批 feedback 负责，_advance_to_phase 不该额外追加"""
        before = len(engine.STORE.get(self.demand_id)["history"])
        engine._advance_to_phase(self.demand_id, engine.PHASE_CODING)
        after = len(engine.STORE.get(self.demand_id)["history"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
