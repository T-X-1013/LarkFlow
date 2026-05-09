"""Step 3 sanity 检查：phase0_inventory.md prompt 在 contract 上不会漂走。

Phase 0 inventory 的下游是 Phase 1 design — design 会按 schema 解 code_map JSON，
所以 prompt 上若：
- 文件丢失 / 无法加载
- Role / Output Schema 关键章节被删
- 工具预算被无意识扩大（run_bash 解禁 / file_editor 写权限放出去）
- 输出格式不再是单一 ```json 块

…design 阶段就会拿到脏数据。这里把上述硬约束钉死。
"""
from __future__ import annotations

import re
import unittest

from pipeline.core.engine import load_prompt


class Phase0InventoryPromptTestCase(unittest.TestCase):
    def setUp(self):
        self.text = load_prompt("phase0_inventory.md")

    def test_prompt_loads_and_is_non_trivial(self):
        self.assertGreater(len(self.text), 1500, "phase0 prompt looks suspiciously short")

    def test_role_and_goal_sections_present(self):
        self.assertIn("# Role: Code Inventory Analyst", self.text)
        self.assertIn("## Primary Goal", self.text)
        self.assertIn("## Tool Budget", self.text)
        self.assertIn("## Output Schema", self.text)
        self.assertIn("## Forbidden", self.text)

    def test_schema_keys_are_declared(self):
        """code_map 的核心字段必须在 prompt 内能找到，否则 design 阶段会拿到结构对不上的 JSON"""
        for key in (
            "repo_mode",
            "scan_root",
            "existing_domains",
            "existing_apis",
            "existing_tables",
            "naming_conventions",
            "tech_debt_hotspots",
            "recommended_touch_points",
        ):
            self.assertIn(f'"{key}"', self.text, f"schema key {key!r} missing from prompt")

    def test_tool_budget_locks_down_dangerous_tools(self):
        """run_bash 在 inventory 阶段被显式禁用；file_editor 只允许 read"""
        self.assertRegex(self.text, r"run_bash[^\n]*forbidden", "run_bash must be forbidden in phase 0")
        # file_editor 仅允许 read
        self.assertIn("file_editor` action `read`", self.text)

    def test_output_format_demands_single_json_block(self):
        """最终消息必须是一个 ```json 块；prompt 至少要包含一个 ```json 围栏作为示例"""
        self.assertIn("```json", self.text)
        # 防止"前面写一段话再贴 JSON"被默认接受
        self.assertRegex(
            self.text,
            r"fenced ```json block must be the entire final message",
        )

    def test_worked_example_json_is_parseable(self):
        """文档里的 worked example JSON 必须自身合法，否则 LLM 会抄成废话"""
        import json

        json_blocks = re.findall(r"```json\s*\n(.*?)\n```", self.text, flags=re.DOTALL)
        self.assertGreaterEqual(len(json_blocks), 2, "expected schema sample + worked example")
        for idx, block in enumerate(json_blocks):
            try:
                json.loads(block)
            except json.JSONDecodeError as exc:
                self.fail(f"json block #{idx} not parseable: {exc}\n{block[:200]}")


if __name__ == "__main__":
    unittest.main()
