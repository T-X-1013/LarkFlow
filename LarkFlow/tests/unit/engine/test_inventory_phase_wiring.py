"""Step 8 验收：inventory 编排 + code_map 注入 + regress 路由。

钉死的合约：
1. _extract_code_map_from_history 能解析最末 assistant 消息里的 ```json 块。
2. _render_code_map_block 把 dict 渲染成 <code-map>...</code-map>，缺失时返回空串。
3. _try_regress 在 brownfield 模板下返回 "inventory"，在 feature 模板下返回 "coding"。
4. _should_run_inventory 严格按 (repo_mode, ctl.template) 二维判定，缺一不可。
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from pipeline.core import engine, engine_control
from pipeline.core.engine import (
    _extract_code_map_from_history,
    _render_code_map_block,
    _should_run_inventory,
    _try_regress,
)


class ExtractCodeMapTestCase(unittest.TestCase):
    def test_returns_none_when_no_json_block(self):
        session = {"history": [{"role": "assistant", "content": "no json here"}]}
        self.assertIsNone(_extract_code_map_from_history(session))

    def test_parses_single_json_block_string_content(self):
        payload = {"repo_mode": "brownfield", "existing_domains": [{"name": "user"}]}
        session = {
            "history": [
                {"role": "user", "content": "scan plz"},
                {"role": "assistant", "content": f"```json\n{json.dumps(payload)}\n```"},
            ]
        }
        self.assertEqual(_extract_code_map_from_history(session), payload)

    def test_parses_anthropic_block_list_content(self):
        payload = {"repo_mode": "brownfield", "existing_domains": []}
        session = {
            "history": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "intro"},
                        {"type": "text", "text": f"```json\n{json.dumps(payload)}\n```"},
                    ],
                }
            ]
        }
        self.assertEqual(_extract_code_map_from_history(session), payload)

    def test_uses_last_assistant_message(self):
        old = {"repo_mode": "brownfield", "tag": "old"}
        new = {"repo_mode": "brownfield", "tag": "new"}
        session = {
            "history": [
                {"role": "assistant", "content": f"```json\n{json.dumps(old)}\n```"},
                {"role": "user", "content": "actually rerun"},
                {"role": "assistant", "content": f"```json\n{json.dumps(new)}\n```"},
            ]
        }
        self.assertEqual(_extract_code_map_from_history(session)["tag"], "new")

    def test_invalid_json_returns_none(self):
        session = {
            "history": [
                {"role": "assistant", "content": "```json\n{not json}\n```"},
            ]
        }
        self.assertIsNone(_extract_code_map_from_history(session))


class RenderCodeMapBlockTestCase(unittest.TestCase):
    def test_empty_when_code_map_missing(self):
        self.assertEqual(_render_code_map_block(None), "")
        self.assertEqual(_render_code_map_block({}), "")

    def test_wraps_with_code_map_tag_and_includes_payload(self):
        payload = {"repo_mode": "brownfield", "existing_domains": [{"name": "user"}]}
        block = _render_code_map_block(payload)
        self.assertTrue(block.startswith("<code-map>\n"))
        self.assertIn("</code-map>", block)
        self.assertIn('"repo_mode": "brownfield"', block)
        self.assertIn("user", block)


class ShouldRunInventoryTestCase(unittest.TestCase):
    def test_returns_false_for_greenfield(self):
        # repo_mode 为 greenfield 时，无论 ctl 怎么样都不进入 inventory
        self.assertFalse(_should_run_inventory("any", "greenfield"))

    def test_returns_false_when_no_ctl(self):
        with patch.object(engine, "get_pipeline_control", return_value=None):
            self.assertFalse(_should_run_inventory("missing", "brownfield"))

    def test_returns_false_when_template_is_feature(self):
        ctl = MagicMock(template="feature")
        with patch.object(engine, "get_pipeline_control", return_value=ctl):
            self.assertFalse(_should_run_inventory("d1", "brownfield"))

    def test_returns_true_when_brownfield_template_and_brownfield_repo(self):
        ctl = MagicMock(template="brownfield")
        with patch.object(engine, "get_pipeline_control", return_value=ctl):
            self.assertTrue(_should_run_inventory("d1", "brownfield"))


class TryRegressBrownfieldRoutingTestCase(unittest.TestCase):
    """关键回归：brownfield 模板的 review.on_failure.to == 'inventory'，
    _try_regress 必须把它返回出来，否则 Step 7 的 REGRESS 被引擎当成回 coding。"""

    def setUp(self):
        self.store: dict = {"d-bf": {"demand_id": "d-bf", "messages": []}}
        self.logger = MagicMock()

        def loader(demand_id):
            return self.store.get(demand_id)

        def saver(demand_id, session):
            self.store[demand_id] = session

        self._patches = [
            patch("pipeline.core.engine._load_session", side_effect=loader),
            patch("pipeline.core.engine._save_session", side_effect=saver),
            patch(
                "pipeline.core.engine.append_user_text",
                side_effect=lambda s, t: s.setdefault("messages", []).append(
                    {"role": "user", "content": t}
                ),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_brownfield_template_returns_inventory_target(self):
        ctl = MagicMock()
        ctl.template = "brownfield"
        # _try_regress 通过 `from pipeline.core import engine_control; engine_control.get(...)` 取 ctl
        with patch.object(engine_control, "get", return_value=ctl):
            target = _try_regress("d-bf", "design empty", self.logger)
        self.assertEqual(target, "inventory")
        # 历史里也应记录 to=inventory
        self.assertEqual(
            self.store["d-bf"]["regression"]["history"][-1]["to"],
            "inventory",
        )

    def test_feature_template_still_returns_coding_target(self):
        ctl = MagicMock()
        ctl.template = "feature"
        with patch.object(engine_control, "get", return_value=ctl):
            target = _try_regress("d-bf", "kratos layering bug", self.logger)
        self.assertEqual(target, "coding")


if __name__ == "__main__":
    unittest.main()
