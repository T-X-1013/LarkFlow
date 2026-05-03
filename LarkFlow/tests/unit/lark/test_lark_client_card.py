"""
`pipeline.lark.client.build_approval_card` 的渲染分支测试

覆盖 Step 2 的两条路径：
1. 传入 tech_doc_url → 卡片 markdown 含可点击链接，不截断 design_doc
2. 未传 tech_doc_url → 回退到旧"截断 500 字"行为（向后兼容）
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from pipeline.lark import client as lark_client
from pipeline.lark.client import build_approval_card, send_lark_card


def _markdown_content(card: dict) -> str:
    elements = card["elements"]
    markdown_elements = [e for e in elements if e.get("tag") == "markdown"]
    assert markdown_elements, "卡片应包含 markdown 元素"
    return markdown_elements[0]["content"]


class BuildApprovalCardTestCase(unittest.TestCase):
    def test_tech_doc_url_renders_clickable_link(self):
        card = build_approval_card(
            "DEMAND-1",
            "summary-text",
            design_doc="这段超长正文不应出现在卡片上" * 100,
            tech_doc_url="https://feishu.cn/docx/docx_abc",
        )
        md = _markdown_content(card)

        self.assertIn("[查看完整技术方案](https://feishu.cn/docx/docx_abc)", md)
        self.assertIn("summary-text", md)
        self.assertNotIn("这段超长正文不应出现在卡片上", md)
        # header 保留原样
        self.assertIn("DEMAND-1", card["header"]["title"]["content"])

    def test_custom_link_title(self):
        card = build_approval_card(
            "DEMAND-2",
            "s",
            tech_doc_url="https://feishu.cn/docx/xxx",
            tech_doc_title="点我看方案",
        )
        self.assertIn("[点我看方案](https://feishu.cn/docx/xxx)", _markdown_content(card))

    def test_without_url_falls_back_to_truncated_doc(self):
        long_doc = "a" * 800
        card = build_approval_card("DEMAND-3", "s", design_doc=long_doc)
        md = _markdown_content(card)

        self.assertIn("详细设计 (部分)", md)
        self.assertIn("a" * 500 + "...", md)
        self.assertNotIn("a" * 501, md)

    def test_short_doc_not_truncated(self):
        card = build_approval_card("DEMAND-4", "s", design_doc="short body")
        self.assertIn("short body", _markdown_content(card))
        self.assertNotIn("...", _markdown_content(card))

    def test_actions_preserved(self):
        card = build_approval_card(
            "DEMAND-5", "s", tech_doc_url="https://x/docx/y"
        )
        actions = [e for e in card["elements"] if e.get("tag") == "action"]
        self.assertEqual(len(actions), 1)
        action_values = [a["value"]["action"] for a in actions[0]["actions"]]
        self.assertEqual(action_values, ["approve", "reject"])


class SendLarkCardTestCase(unittest.TestCase):
    def test_passes_tech_doc_url_through(self):
        captured = {}

        def fake_send(target, msg_type, content, receive_id_type=None):
            captured["target"] = target
            captured["msg_type"] = msg_type
            captured["content"] = content
            return {"code": 0, "msg": "ok", "data": None}

        with patch.object(lark_client, "_send_message", side_effect=fake_send):
            result = send_lark_card(
                "ou_abc",
                "DEMAND-1",
                "s",
                tech_doc_url="https://feishu.cn/docx/t",
            )

        self.assertEqual(result["code"], 0)
        self.assertEqual(captured["msg_type"], "interactive")
        md = _markdown_content(captured["content"])
        self.assertIn("https://feishu.cn/docx/t", md)

    def test_backward_compatible_positional_call(self):
        """engine.py 现有 send_lark_card(target, id, summary, design_doc) 调用应继续工作"""
        with patch.object(
            lark_client, "_send_message", return_value={"code": 0, "msg": "ok", "data": None}
        ) as mock_send:
            send_lark_card("ou_x", "D1", "summary", "design body")

        # _send_message 被调用且 content 是 dict（JSON 结构而非字符串）
        args = mock_send.call_args.args
        self.assertEqual(args[0], "ou_x")
        self.assertEqual(args[1], "interactive")
        self.assertIsInstance(args[2], dict)


if __name__ == "__main__":
    unittest.main()
