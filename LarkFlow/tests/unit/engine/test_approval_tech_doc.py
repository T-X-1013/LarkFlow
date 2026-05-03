"""
Step 3 测试：engine 的 tech doc 准备 + ask_human_approval 分支串联

覆盖：
1. `_prepare_tech_doc` 三个分支：复用缓存 / 成功建文档并授权 / 建文档失败降级
2. ask_human_approval tool call 触发后：
   - send_lark_card 用正确的 tech_doc_url 调用
   - pending_approval 落盘字段含 tech_doc_token / tech_doc_url
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from pipeline.core import engine
from pipeline.lark.doc_client import LarkDocWriteError


class PrepareTechDocTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()

    def test_reuse_existing_url(self):
        with patch.object(engine, "create_tech_doc") as mock_create, \
             patch.object(engine, "grant_doc_access") as mock_grant:
            token, url = engine._prepare_tech_doc(
                "D1",
                "body",
                self.logger,
                existing_token="tok_old",
                existing_url="https://x/docx/tok_old",
            )
        self.assertEqual(token, "tok_old")
        self.assertEqual(url, "https://x/docx/tok_old")
        mock_create.assert_not_called()
        mock_grant.assert_not_called()

    def test_create_success_with_grant_open_id(self):
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_new", "https://x/docx/tok_new")
        ) as mock_create, \
             patch.object(engine, "grant_doc_access") as mock_grant, \
             patch.dict(os.environ, {
                 "LARK_DEMAND_APPROVE_TARGET": "ou_approver",
                 "LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE": "open_id",
             }):
            token, url = engine._prepare_tech_doc("D2", "body", self.logger)

        self.assertEqual((token, url), ("tok_new", "https://x/docx/tok_new"))
        mock_create.assert_called_once()
        mock_grant.assert_called_once_with(
            "tok_new", "ou_approver", member_type="openid", perm="full_access"
        )

    def test_create_success_with_grant_chat_id(self):
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_c", "https://x/docx/tok_c")
        ), patch.object(engine, "grant_doc_access") as mock_grant, \
             patch.dict(os.environ, {
                 "LARK_DEMAND_APPROVE_TARGET": "oc_chat",
                 "LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE": "chat_id",
             }):
            engine._prepare_tech_doc("D2b", "body", self.logger)

        mock_grant.assert_called_once_with(
            "tok_c", "oc_chat", member_type="openchat", perm="full_access"
        )

    def test_create_failure_degrades(self):
        with patch.object(
            engine, "create_tech_doc", side_effect=LarkDocWriteError("boom")
        ), patch.object(engine, "grant_doc_access") as mock_grant:
            token, url = engine._prepare_tech_doc("D3", "body", self.logger)

        self.assertEqual((token, url), (None, None))
        mock_grant.assert_not_called()
        # 告警已打
        self.logger.warning.assert_called()

    def test_grant_failure_keeps_url(self):
        """授权失败不应回滚文档；仍返回 (token, url) 让卡片发出"""
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_g", "https://x/docx/tok_g")
        ), patch.object(
            engine, "grant_doc_access", side_effect=LarkDocWriteError("deny")
        ), patch.dict(os.environ, {"LARK_DEMAND_APPROVE_TARGET": "ou_x"}):
            token, url = engine._prepare_tech_doc("D4", "body", self.logger)

        self.assertEqual((token, url), ("tok_g", "https://x/docx/tok_g"))
        self.logger.warning.assert_called()

    def test_writeback_to_base_when_record_id_present(self):
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_wb", "https://x/docx/tok_wb")
        ), patch.object(engine, "grant_doc_access"), \
             patch("pipeline.lark.bitable_listener.update_demand_tech_doc_url") as mock_writeback, \
             patch.dict(os.environ, {"LARK_DEMAND_APPROVE_TARGET": "ou_x"}):
            mock_writeback.return_value = True
            token, url = engine._prepare_tech_doc(
                "D6", "body", self.logger, record_id="recXYZ"
            )

        self.assertEqual((token, url), ("tok_wb", "https://x/docx/tok_wb"))
        mock_writeback.assert_called_once_with("recXYZ", "https://x/docx/tok_wb")

    def test_no_writeback_when_record_id_missing(self):
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_nw", "https://x/docx/tok_nw")
        ), patch.object(engine, "grant_doc_access"), \
             patch("pipeline.lark.bitable_listener.update_demand_tech_doc_url") as mock_writeback, \
             patch.dict(os.environ, {"LARK_DEMAND_APPROVE_TARGET": "ou_x"}):
            engine._prepare_tech_doc("D7", "body", self.logger, record_id=None)

        mock_writeback.assert_not_called()

    def test_writeback_failure_does_not_break(self):
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_f", "https://x/docx/tok_f")
        ), patch.object(engine, "grant_doc_access"), \
             patch(
                 "pipeline.lark.bitable_listener.update_demand_tech_doc_url",
                 return_value=False,
             ), patch.dict(os.environ, {"LARK_DEMAND_APPROVE_TARGET": "ou_x"}):
            token, url = engine._prepare_tech_doc(
                "D8", "body", self.logger, record_id="recF"
            )
        # 返回值不受回写失败影响
        self.assertEqual((token, url), ("tok_f", "https://x/docx/tok_f"))
        self.logger.warning.assert_called()

    def test_no_target_env_logs_warning_but_keeps_url(self):
        with patch.object(
            engine, "create_tech_doc", return_value=("tok_n", "https://x/docx/tok_n")
        ), patch.object(engine, "grant_doc_access") as mock_grant, \
             patch.dict(os.environ, {"LARK_DEMAND_APPROVE_TARGET": ""}):
            token, url = engine._prepare_tech_doc("D5", "body", self.logger)

        self.assertEqual((token, url), ("tok_n", "https://x/docx/tok_n"))
        mock_grant.assert_not_called()
        self.logger.warning.assert_called()


class AskHumanApprovalBranchTestCase(unittest.TestCase):
    """
    `run_agent_loop` 中 ask_human_approval 分支的行为测试

    策略：mock 掉 STORE / _create_turn_with_retry / send_lark_card / _prepare_tech_doc，
    用一次 tool_calls=[ask_human_approval] 的假 turn 驱动一次循环后返回 False
    """

    def _make_turn(self, tool_call_id="tc-1"):
        turn = MagicMock()
        turn.usage = {}
        turn.finished = False
        turn.text_blocks = []
        tool_call = MagicMock()
        tool_call.id = tool_call_id
        tool_call.name = "ask_human_approval"
        tool_call.arguments = {"summary": "方案摘要", "design_doc": "技术方案正文 ..."}
        turn.tool_calls = [tool_call]
        return turn

    def _make_session(self, pending=None):
        return {
            "logger": MagicMock(),
            "phase": "design",
            "pending_approval": pending,
        }

    def test_sends_card_with_tech_doc_url_and_persists_pending(self):
        session = self._make_session()
        save_calls = []

        with patch.object(engine, "_load_session", return_value=session), \
             patch.object(engine, "_save_session", side_effect=lambda d, s: save_calls.append(s.copy())), \
             patch.object(engine, "_create_turn_with_retry", return_value=self._make_turn()), \
             patch.object(
                 engine,
                 "_prepare_tech_doc",
                 return_value=("tok_ok", "https://x/docx/tok_ok"),
             ) as mock_prep, \
             patch.object(engine, "send_lark_card") as mock_send, \
             patch.dict(os.environ, {"LARK_CHAT_ID": "ou_approver"}):
            completed = engine.run_agent_loop("D-AH-1", "sys prompt")

        self.assertFalse(completed)
        mock_prep.assert_called_once()
        # 发卡时 tech_doc_url 透传
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs.get("tech_doc_url"), "https://x/docx/tok_ok")
        self.assertEqual(kwargs.get("design_doc"), "技术方案正文 ...")

        # pending_approval 含 token/url
        self.assertEqual(session["pending_approval"]["tech_doc_token"], "tok_ok")
        self.assertEqual(
            session["pending_approval"]["tech_doc_url"], "https://x/docx/tok_ok"
        )
        self.assertEqual(session["pending_approval"]["tool_call_id"], "tc-1")

    def test_degrade_path_still_sends_card(self):
        session = self._make_session()

        with patch.object(engine, "_load_session", return_value=session), \
             patch.object(engine, "_save_session"), \
             patch.object(engine, "_create_turn_with_retry", return_value=self._make_turn()), \
             patch.object(engine, "_prepare_tech_doc", return_value=(None, None)), \
             patch.object(engine, "send_lark_card") as mock_send, \
             patch.dict(os.environ, {"LARK_CHAT_ID": "ou_approver"}):
            engine.run_agent_loop("D-AH-2", "sys prompt")

        _, kwargs = mock_send.call_args
        self.assertIsNone(kwargs.get("tech_doc_url"))
        # design_doc 原样传入（lark_client 会走截断分支）
        self.assertEqual(kwargs.get("design_doc"), "技术方案正文 ...")

    def test_reuses_cached_tech_doc(self):
        session = self._make_session(
            pending={
                "tech_doc_token": "tok_prev",
                "tech_doc_url": "https://x/docx/tok_prev",
            }
        )

        with patch.object(engine, "_load_session", return_value=session), \
             patch.object(engine, "_save_session"), \
             patch.object(engine, "_create_turn_with_retry", return_value=self._make_turn()), \
             patch.object(engine, "create_tech_doc") as mock_create, \
             patch.object(engine, "send_lark_card") as mock_send, \
             patch.dict(os.environ, {"LARK_CHAT_ID": "ou_approver"}):
            engine.run_agent_loop("D-AH-3", "sys prompt")

        mock_create.assert_not_called()
        _, kwargs = mock_send.call_args
        self.assertEqual(kwargs.get("tech_doc_url"), "https://x/docx/tok_prev")


if __name__ == "__main__":
    unittest.main()
