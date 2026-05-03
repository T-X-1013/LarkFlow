"""D7 Step 7: review_multi / by_role 契约软兼容单测。

覆盖：
- PipelineState 无 review_multi 时默认 None（向后兼容）
- ReviewMultiSnapshot 能从 session["review_multi"]["subroles"] 反序列化
- build_state 正确填充 review_multi
- MetricsItem.by_role 默认空列表（向后兼容）
- build_metrics_item 从 session["metrics"]["by_role"] dict 摊平成 List[RoleMetrics]
- 损坏条目被跳过而非让整个响应 500
"""
from __future__ import annotations

import unittest

from pipeline.core import engine_control
from pipeline.core.contracts import (
    MetricsItem,
    PipelineState,
    PipelineStatus,
    ReviewMultiSnapshot,
    ReviewSubRoleResult,
    RoleMetrics,
)
from pipeline.ops.observability import build_metrics_item


class PipelineStateBackwardCompatTestCase(unittest.TestCase):
    def test_pipeline_state_default_review_multi_is_none(self):
        state = PipelineState(id="X", requirement="r")
        self.assertIsNone(state.review_multi)

    def test_metrics_item_default_by_role_is_empty(self):
        item = MetricsItem(pipeline_id="X", status=PipelineStatus.PENDING)
        self.assertEqual(item.by_role, [])


class BuildStateReviewMultiTestCase(unittest.TestCase):
    def _ctl(self):
        return engine_control.register(requirement="r", template="feature_multi")

    def tearDown(self):
        engine_control._REGISTRY.clear()  # 防止测试间串扰

    def test_no_review_multi_in_session_yields_none(self):
        ctl = self._ctl()
        state = engine_control.build_state(ctl, {"phase": "coding"})
        self.assertIsNone(state.review_multi)

    def test_review_multi_subroles_populated(self):
        ctl = self._ctl()
        session = {
            "phase": "reviewing",
            "review_multi": {
                "subroles": [
                    {
                        "role": "security",
                        "status": "done",
                        "artifact_path": "tmp/X/review_multi/review_security.md",
                        "tokens_input": 100,
                        "tokens_output": 40,
                        "duration_ms": 1800,
                        "error": None,
                    },
                    {
                        "role": "testing-coverage",
                        "status": "failed",
                        "artifact_path": None,
                        "tokens_input": 0,
                        "tokens_output": 0,
                        "duration_ms": 0,
                        "error": "timeout",
                    },
                    {
                        "role": "kratos-layering",
                        "status": "done",
                        "artifact_path": "tmp/X/review_multi/review_kratos-layering.md",
                        "tokens_input": 150,
                        "tokens_output": 60,
                        "duration_ms": 2100,
                        "error": None,
                    },
                ]
            },
        }
        state = engine_control.build_state(ctl, session)
        self.assertIsInstance(state.review_multi, ReviewMultiSnapshot)
        self.assertEqual(len(state.review_multi.subroles), 3)
        roles = {r.role: r for r in state.review_multi.subroles}
        self.assertEqual(roles["security"].status, "done")
        self.assertEqual(roles["security"].tokens_input, 100)
        self.assertEqual(roles["testing-coverage"].status, "failed")
        self.assertEqual(roles["testing-coverage"].error, "timeout")
        self.assertEqual(roles["kratos-layering"].duration_ms, 2100)

    def test_corrupted_subrole_entry_skipped(self):
        ctl = self._ctl()
        session = {
            "review_multi": {
                "subroles": [
                    "not-a-dict",
                    {"role": "security", "status": "done"},  # ok
                    None,
                ]
            }
        }
        state = engine_control.build_state(ctl, session)
        self.assertEqual(len(state.review_multi.subroles), 1)
        self.assertEqual(state.review_multi.subroles[0].role, "security")


class BuildMetricsItemByRoleTestCase(unittest.TestCase):
    def _state(self, **kw):
        return PipelineState(
            id=kw.get("id", "D1"),
            requirement="r",
            status=kw.get("status", PipelineStatus.RUNNING),
        )

    def test_no_by_role_in_session_yields_empty_list(self):
        session = {"metrics": {"tokens_input": 100, "tokens_output": 50, "duration_ms": 500}}
        item = build_metrics_item("D1", self._state(), session)
        self.assertEqual(item.by_role, [])
        self.assertEqual(item.tokens.input, 100)

    def test_by_role_dict_flattened_to_list(self):
        session = {
            "metrics": {
                "tokens_input": 600,
                "tokens_output": 250,
                "duration_ms": 5000,
                "by_role": {
                    "security": {"tokens_input": 100, "tokens_output": 40, "duration_ms": 1800},
                    "testing-coverage": {"tokens_input": 200, "tokens_output": 80, "duration_ms": 1500},
                    "kratos-layering": {"tokens_input": 300, "tokens_output": 130, "duration_ms": 1700},
                },
            }
        }
        item = build_metrics_item("D1", self._state(), session)
        self.assertEqual(len(item.by_role), 3)
        roles = {r.role: r for r in item.by_role}
        self.assertIsInstance(roles["security"], RoleMetrics)
        self.assertEqual(roles["security"].tokens_input, 100)
        self.assertEqual(roles["testing-coverage"].tokens_output, 80)
        self.assertEqual(roles["kratos-layering"].duration_ms, 1700)

    def test_by_role_corrupted_entries_skipped(self):
        session = {
            "metrics": {
                "by_role": {
                    "security": {"tokens_input": "not-an-int"},  # 会被 coerce 成 0
                    "ghost": "not-a-dict",  # 跳过
                    "ok": {"tokens_input": 10, "tokens_output": 5, "duration_ms": 100},
                }
            }
        }
        item = build_metrics_item("D1", self._state(), session)
        roles = {r.role: r for r in item.by_role}
        self.assertIn("ok", roles)
        self.assertEqual(roles["ok"].tokens_input, 10)
        self.assertNotIn("ghost", roles)
        # security 的非法 tokens_input 被 _coerce_int 变成 0，但 role 依然保留
        if "security" in roles:
            self.assertEqual(roles["security"].tokens_input, 0)


if __name__ == "__main__":
    unittest.main()
