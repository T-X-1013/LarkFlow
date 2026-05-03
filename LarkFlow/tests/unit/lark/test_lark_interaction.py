"""
飞书事件处理层测试

迁移到 lark-oapi SDK + WebSocket 长连后，URL 校验、verification token、
签名校验均由 SDK 负责，这里只覆盖业务层：
1. 卡片 action 的幂等去重（SQLite 层）
2. approve/reject 的派发行为
3. WebSocket 回调能正确解析 P2CardActionTrigger 事件并调用业务处理
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

from pipeline.lark.interaction import (
    _on_card_action,
    process_card_action,
)


class LarkInteractionTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.temp_dir.name, "lark_event_store.db")
        self._env_patch = patch.dict(
            os.environ,
            {"LARK_EVENT_STORE_PATH": self.store_path},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self.temp_dir.cleanup()

    def test_approve_action_dispatches_resume_and_returns_status_card(self):
        resume_calls = []

        def immediate_runner(target):
            target()

        def fake_resume(demand_id, approved, feedback):
            resume_calls.append((demand_id, approved, feedback))

        with patch(
            "pipeline.lark.interaction._launch_background_task",
            side_effect=immediate_runner,
        ), patch(
            "pipeline.lark.interaction.time.sleep",
            return_value=None,
        ), patch(
            "pipeline.core.engine.resume_after_approval",
            side_effect=fake_resume,
        ):
            card = process_card_action(
                "evt-approve-001",
                {"action": "approve", "demand_id": "DEMAND-B5"},
            )

        self.assertEqual(len(resume_calls), 1)
        self.assertEqual(resume_calls[0][0], "DEMAND-B5")
        self.assertTrue(resume_calls[0][1])
        self.assertIn("已通过审批", card["elements"][0]["content"])

    def test_reject_action_dispatches_resume_with_approved_false(self):
        resume_calls = []

        def immediate_runner(target):
            target()

        def fake_resume(demand_id, approved, feedback):
            resume_calls.append((demand_id, approved, feedback))

        with patch(
            "pipeline.lark.interaction._launch_background_task",
            side_effect=immediate_runner,
        ), patch(
            "pipeline.lark.interaction.time.sleep",
            return_value=None,
        ), patch(
            "pipeline.core.engine.resume_after_approval",
            side_effect=fake_resume,
        ):
            card = process_card_action(
                "evt-reject-001",
                {"action": "reject", "demand_id": "DEMAND-B5"},
            )

        self.assertEqual(len(resume_calls), 1)
        self.assertFalse(resume_calls[0][1])
        self.assertIn("驳回", card["elements"][0]["content"])

    def test_duplicate_event_id_only_resumes_once(self):
        resume_calls = []

        def immediate_runner(target):
            target()

        def fake_resume(demand_id, approved, feedback):
            resume_calls.append((demand_id, approved, feedback))

        with patch(
            "pipeline.lark.interaction._launch_background_task",
            side_effect=immediate_runner,
        ), patch(
            "pipeline.lark.interaction.time.sleep",
            return_value=None,
        ), patch(
            "pipeline.core.engine.resume_after_approval",
            side_effect=fake_resume,
        ):
            payload = {"action": "approve", "demand_id": "DEMAND-B5"}
            card_first = process_card_action("evt-dup-001", payload)
            card_second = process_card_action("evt-dup-001", payload)
            card_third = process_card_action("evt-dup-001", payload)

        self.assertEqual(len(resume_calls), 1)
        self.assertIn("已通过审批", card_first["elements"][0]["content"])
        self.assertIn("请勿重复点击", card_second["elements"][0]["content"])
        self.assertIn("请勿重复点击", card_third["elements"][0]["content"])

    def test_invalid_action_value_returns_parse_error_card(self):
        card = process_card_action("evt-bad-001", {"action": "", "demand_id": ""})
        self.assertIn("解析失败", card["elements"][0]["content"])

    def test_unsupported_action_returns_unsupported_message(self):
        card = process_card_action(
            "evt-unknown-001",
            {"action": "other", "demand_id": "DEMAND-B5"},
        )
        self.assertIn("unsupported action", card["elements"][0]["content"])

    def test_on_card_action_parses_sdk_event_and_returns_response(self):
        sdk_event = P2CardActionTrigger(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-sdk-001",
                    "event_type": "card.action.trigger",
                },
                "event": {
                    "action": {
                        "value": {"action": "approve", "demand_id": "DEMAND-B5"},
                    }
                },
            }
        )
        resume_calls = []

        def immediate_runner(target):
            target()

        def fake_resume(demand_id, approved, feedback):
            resume_calls.append((demand_id, approved, feedback))

        with patch(
            "pipeline.lark.interaction._launch_background_task",
            side_effect=immediate_runner,
        ), patch(
            "pipeline.lark.interaction.time.sleep",
            return_value=None,
        ), patch(
            "pipeline.core.engine.resume_after_approval",
            side_effect=fake_resume,
        ):
            response = _on_card_action(sdk_event)

        self.assertEqual(len(resume_calls), 1)
        self.assertEqual(response.card.type, "raw")
        self.assertIn("已通过审批", response.card.data["elements"][0]["content"])


if __name__ == "__main__":
    unittest.main()
