"""D7 Step 2: 子 session 机制单测。

覆盖：
- subsession_key 拼接 + 非法输入拒绝
- is_subsession_key / parse_subsession_key 往返一致
- init_subsession 正确继承只读上下文、新开运行时状态
- save_subsession / load_subsession 通过真实 SqliteSessionStore 往返
- finalize_subsession 落 terminal_phase，list_active 不再返回
- merge_subsession_metrics tokens 精确累加 + by_role 维度独立记录
- 多 role 子 session 之间互不污染
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.persistence import SqliteSessionStore
from pipeline.subsession import (
    SUBSESSION_ROLE_SEP,
    finalize_subsession,
    init_subsession,
    is_subsession_key,
    load_subsession,
    merge_subsession_metrics,
    parse_subsession_key,
    save_subsession,
    subsession_key,
)


class SubsessionKeyTestCase(unittest.TestCase):
    def test_key_composition(self):
        self.assertEqual(
            subsession_key("D42", "security"),
            f"D42{SUBSESSION_ROLE_SEP}security",
        )

    def test_key_rejects_empty_parent(self):
        with self.assertRaises(ValueError):
            subsession_key("", "security")

    def test_key_rejects_empty_role(self):
        with self.assertRaises(ValueError):
            subsession_key("D1", "")
        with self.assertRaises(ValueError):
            subsession_key("D1", "   ")

    def test_key_rejects_role_with_double_colon(self):
        with self.assertRaises(ValueError):
            subsession_key("D1", "sec::urity")

    def test_is_subsession_key(self):
        self.assertTrue(is_subsession_key("D1::review::security"))
        self.assertFalse(is_subsession_key("D1"))
        self.assertFalse(is_subsession_key(""))
        self.assertFalse(is_subsession_key(None))  # type: ignore[arg-type]

    def test_parse_roundtrip(self):
        k = subsession_key("D99", "kratos-layering")
        self.assertEqual(parse_subsession_key(k), ("D99", "kratos-layering"))

    def test_parse_non_subsession_returns_none(self):
        self.assertIsNone(parse_subsession_key("D1"))


class InitSubsessionTestCase(unittest.TestCase):
    def _parent(self):
        return {
            "demand_id": "D42",
            "provider": "openai",
            "target_dir": "/workspace/demo-app",
            "workspace_root": "/workspace",
            "history": [{"role": "user", "content": "some parent history"}],
            "metrics": {"tokens_input": 1000, "tokens_output": 500},
            "phase": "reviewing",
            "pending_approval": {"summary": "parent pending"},
        }

    def test_inherits_readonly_context(self):
        sub = init_subsession(self._parent(), "security")
        self.assertEqual(sub["parent_demand_id"], "D42")
        self.assertEqual(sub["role"], "security")
        self.assertEqual(sub["provider"], "openai")
        self.assertEqual(sub["target_dir"], "/workspace/demo-app")
        self.assertEqual(sub["workspace_root"], "/workspace")
        self.assertEqual(sub["demand_id"], "D42::review::security")

    def test_opens_fresh_runtime_state(self):
        sub = init_subsession(self._parent(), "security")
        self.assertEqual(sub["history"], [])
        self.assertEqual(sub["metrics"], {"tokens_input": 0, "tokens_output": 0})
        self.assertIsNone(sub["pending_approval"])
        self.assertTrue(sub["hitl_disabled"])
        self.assertEqual(sub["phase"], "reviewing")

    def test_parent_mutation_does_not_affect_sub(self):
        parent = self._parent()
        sub = init_subsession(parent, "security")
        parent["history"].append({"role": "assistant", "content": "new"})
        parent["metrics"]["tokens_input"] = 9999
        # 子 session 不应被污染
        self.assertEqual(sub["history"], [])
        self.assertEqual(sub["metrics"]["tokens_input"], 0)

    def test_rejects_parent_without_demand_id(self):
        with self.assertRaises(ValueError):
            init_subsession({"provider": "openai"}, "security")

    def test_rejects_parent_without_provider(self):
        with self.assertRaises(ValueError):
            init_subsession({"demand_id": "D1"}, "security")


class SubsessionStoreRoundtripTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="larkflow-subsession-")
        self.db_path = str(Path(self._tmp.name) / "sessions.db")
        self.store = SqliteSessionStore(self.db_path)
        self.parent = {
            "demand_id": "D42",
            "provider": "openai",
            "target_dir": "/t",
            "workspace_root": "/w",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_then_load(self):
        sub = init_subsession(self.parent, "security")
        sub["history"].append({"role": "user", "content": "role-specific"})
        sub["metrics"]["tokens_input"] = 100
        save_subsession(self.store, "D42", "security", sub)

        got = load_subsession(self.store, "D42", "security")
        self.assertIsNotNone(got)
        self.assertEqual(got["role"], "security")
        self.assertEqual(got["history"][0]["content"], "role-specific")
        self.assertEqual(got["metrics"]["tokens_input"], 100)

    def test_multiple_roles_isolated(self):
        for role in ("security", "testing-coverage", "kratos-layering"):
            s = init_subsession(self.parent, role)
            s["metrics"]["tokens_input"] = {"security": 10, "testing-coverage": 20, "kratos-layering": 30}[role]
            s["history"].append({"role": "assistant", "content": role})
            save_subsession(self.store, "D42", role, s)

        a = load_subsession(self.store, "D42", "security")
        b = load_subsession(self.store, "D42", "testing-coverage")
        c = load_subsession(self.store, "D42", "kratos-layering")
        self.assertEqual(a["metrics"]["tokens_input"], 10)
        self.assertEqual(b["metrics"]["tokens_input"], 20)
        self.assertEqual(c["metrics"]["tokens_input"], 30)
        self.assertEqual(a["history"][0]["content"], "security")
        self.assertEqual(b["history"][0]["content"], "testing-coverage")
        self.assertEqual(c["history"][0]["content"], "kratos-layering")

    def test_subsession_does_not_overwrite_parent(self):
        # 先写主 session
        parent_stored = {
            "demand_id": "D42",
            "provider": "openai",
            "phase": "reviewing",
            "metrics": {"tokens_input": 500, "tokens_output": 250},
        }
        self.store.save("D42", parent_stored)

        sub = init_subsession(self.parent, "security")
        sub["metrics"]["tokens_input"] = 999
        save_subsession(self.store, "D42", "security", sub)

        # 主 session 未被污染
        p = self.store.get("D42")
        self.assertEqual(p["metrics"]["tokens_input"], 500)

    def test_finalize_excludes_from_list_active(self):
        # 主 session 保持 active（phase=reviewing）
        self.store.save("D42", {"provider": "openai", "phase": "reviewing"})
        sub = init_subsession(self.parent, "security")
        save_subsession(self.store, "D42", "security", sub)
        active_before = set(self.store.list_active())
        self.assertIn("D42", active_before)
        self.assertIn("D42::review::security", active_before)

        finalize_subsession(self.store, "D42", "security", sub)

        active_after = set(self.store.list_active())
        self.assertIn("D42", active_after, "parent 应仍为 active")
        self.assertNotIn(
            "D42::review::security",
            active_after,
            "finalize 后子 session 不应再被 list_active 返回",
        )


class MergeMetricsTestCase(unittest.TestCase):
    def test_single_role_merge(self):
        parent = {"metrics": {"tokens_input": 1000, "tokens_output": 500}}
        sub = {"metrics": {"tokens_input": 200, "tokens_output": 80}}
        merge_subsession_metrics(parent, sub, "security", duration_ms=3500)

        self.assertEqual(parent["metrics"]["tokens_input"], 1200)
        self.assertEqual(parent["metrics"]["tokens_output"], 580)
        self.assertEqual(
            parent["metrics"]["by_role"]["security"],
            {"tokens_input": 200, "tokens_output": 80, "duration_ms": 3500},
        )

    def test_three_roles_merge_accumulates(self):
        parent = {"metrics": {"tokens_input": 0, "tokens_output": 0}}
        merge_subsession_metrics(
            parent, {"metrics": {"tokens_input": 100, "tokens_output": 50}}, "security", duration_ms=1000
        )
        merge_subsession_metrics(
            parent, {"metrics": {"tokens_input": 200, "tokens_output": 80}}, "testing-coverage", duration_ms=1500
        )
        merge_subsession_metrics(
            parent, {"metrics": {"tokens_input": 300, "tokens_output": 120}}, "kratos-layering", duration_ms=2000
        )

        # 总量 = 三路之和
        self.assertEqual(parent["metrics"]["tokens_input"], 600)
        self.assertEqual(parent["metrics"]["tokens_output"], 250)
        # by_role 三条并列
        self.assertEqual(set(parent["metrics"]["by_role"].keys()),
                         {"security", "testing-coverage", "kratos-layering"})
        self.assertEqual(parent["metrics"]["by_role"]["testing-coverage"]["tokens_input"], 200)

    def test_merge_missing_metrics_treated_as_zero(self):
        parent = {"metrics": {"tokens_input": 10, "tokens_output": 5}}
        merge_subsession_metrics(parent, {}, "security", duration_ms=0)
        self.assertEqual(parent["metrics"]["tokens_input"], 10)
        self.assertEqual(parent["metrics"]["by_role"]["security"],
                         {"tokens_input": 0, "tokens_output": 0, "duration_ms": 0})

    def test_merge_creates_parent_metrics_if_missing(self):
        parent: dict = {}
        merge_subsession_metrics(
            parent, {"metrics": {"tokens_input": 7, "tokens_output": 3}}, "security"
        )
        self.assertEqual(parent["metrics"]["tokens_input"], 7)
        self.assertEqual(parent["metrics"]["tokens_output"], 3)
        self.assertIn("by_role", parent["metrics"])


if __name__ == "__main__":
    unittest.main()
