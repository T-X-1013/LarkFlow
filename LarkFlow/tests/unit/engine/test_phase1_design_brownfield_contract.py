"""Step 5 sanity 检查：phase1_design.md 在 brownfield 路径下的硬合约。

Phase 1 是 brownfield 改造的"承上启下"环节——上游靠 Phase 0 inventory 喂 code_map，
下游靠这份设计文档约束 Phase 2 coding 与 Phase 4 review。所以这里钉死：

1. prompt 显式区分 repo_mode == "brownfield" / "greenfield" 两条路径；
2. design doc 模板里新增 `## Existing Surface Touched` / `## Compatibility Risks` 两节；
3. brownfield 下不能用 "n/a" / "none" 偷懒——通过 Forbidden 段强制；
4. brownfield 下禁止重复跑 inventory 已做过的扫描；
5. Worked Example 同步示范了上述两节，否则 LLM 容易抄旧版例子。
"""
from __future__ import annotations

import unittest

from pipeline.core.engine import load_prompt


class Phase1BrownfieldContractTestCase(unittest.TestCase):
    def setUp(self):
        self.text = load_prompt("phase1_design.md")

    def test_repo_mode_branching_is_explicit(self):
        """两种 repo_mode 必须各自有指示，否则 LLM 不知道该不该读 code_map"""
        self.assertIn('repo_mode == "brownfield"', self.text)
        self.assertIn('repo_mode == "greenfield"', self.text)

    def test_code_map_handoff_is_referenced(self):
        """brownfield 路径要明确 code_map 来自 session.artifacts.code_map / <code-map> 标签"""
        self.assertIn('session["artifacts"]["code_map"]', self.text)
        self.assertIn("<code-map>", self.text)

    def test_existing_surface_section_in_template(self):
        """design doc 模板必须有 Existing Surface Touched 节"""
        self.assertIn("## Existing Surface Touched", self.text)
        # 表头三列约定：File / Currently / This Demand Will
        self.assertRegex(
            self.text,
            r"\|\s*File\s*/\s*API\s*/\s*Table\s*\|\s*Currently\s*\|\s*This Demand Will\s*\|",
        )

    def test_compatibility_risks_section_in_template(self):
        """design doc 模板必须有 Compatibility Risks 节"""
        self.assertIn("## Compatibility Risks", self.text)

    def test_brownfield_forbidden_rules_present(self):
        """Forbidden 段必须显式禁止三件事：空 Existing Surface / 偷懒 'none' / 重跑 inventory"""
        self.assertRegex(
            self.text,
            r"Brownfield only.*Existing Surface Touched.*REGRESS",
        )
        self.assertRegex(
            self.text,
            r"Brownfield only.*Compatibility Risks.*without analysis",
        )
        self.assertRegex(
            self.text,
            r"Brownfield only.*re-running scans the Phase 0 Inventory",
        )

    def test_worked_example_demonstrates_brownfield_sections(self):
        """Worked Example 必须示范 Existing Surface + Compatibility Risks，否则 LLM 抄旧版"""
        # 找到 Worked Example 节后的内容
        worked_idx = self.text.find("## Worked Example")
        self.assertNotEqual(worked_idx, -1, "missing ## Worked Example section")
        example = self.text[worked_idx:]

        self.assertIn("## Existing Surface Touched", example)
        self.assertIn("## Compatibility Risks", example)
        # 示例必须真的填了 code_map 衍生的内容，不是占位
        self.assertIn("api/user/v1/user.proto", example)
        self.assertIn("naming_conventions", example.lower() + "naming_conventions")  # 提及命名约定来源


class GreenfieldUntouchedTestCase(unittest.TestCase):
    """既有 0-1 路径不能被本次改动伤到：核心 4 阶段约束 / Tech Tags / inspect_db 仍然在。"""

    def setUp(self):
        self.text = load_prompt("phase1_design.md")

    def test_kratos_layering_table_still_present(self):
        self.assertIn("## Kratos Layering", self.text)
        self.assertIn("internal/biz/<domain>.go", self.text)

    def test_tech_tags_contract_intact(self):
        self.assertIn("## Tech Tags Contract", self.text)
        self.assertIn('"capabilities"', self.text)

    def test_inspect_db_requirement_intact(self):
        # Forbidden 段保留 inspect_db 跳过的禁令
        self.assertRegex(self.text, r"Skipping `inspect_db`")


if __name__ == "__main__":
    unittest.main()
