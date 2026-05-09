"""Step 7 sanity 检查：phase4_review.md 的 brownfield 设计预飞检查硬合约。

Phase 4 是 brownfield 兜底——Phase 1 设计阶段没把 Existing Surface / Compatibility
Risks 填好时，Phase 4 必须直接 REGRESS（不读代码），把锅打回设计阶段。这里钉死：

1. 预飞检查在 Workflow 步骤 1 内出现，且明确标注 🔴 BLOCKING；
2. 预飞条款覆盖 Existing Surface Touched + Compatibility Risks 两节；
3. 失败时要求 REGRESS 并跳过 code 检查；
4. checklist 里有顶端的 brownfield 完整性 🔴 规则；
5. 给出独立的 brownfield REGRESS 例子，区别于既有 layering REGRESS 例子；
6. greenfield 路径不被误伤——必须显式说"greenfield 不罚"。
"""
from __future__ import annotations

import unittest

from pipeline.core.engine import load_prompt


class Phase4BrownfieldPreflightTestCase(unittest.TestCase):
    def setUp(self):
        self.text = load_prompt("phase4_review.md")

    def test_preflight_step_present_in_workflow(self):
        """workflow 步骤 1 必须包含 brownfield 预飞段落"""
        self.assertIn("Brownfield design pre-flight", self.text)
        self.assertRegex(self.text, r"Brownfield design pre-flight.*🔴.*BLOCKING")

    def test_preflight_covers_both_required_sections(self):
        self.assertIn("## Existing Surface Touched", self.text)
        self.assertIn("## Compatibility Risks", self.text)

    def test_preflight_demands_regress_and_skips_code_inspection(self):
        """失败时必须 REGRESS 且不进入代码检查"""
        self.assertIn("<review-verdict>REGRESS</review-verdict>", self.text)
        self.assertRegex(
            self.text,
            r"Do NOT proceed to inspect code",
        )

    def test_greenfield_explicitly_not_penalized(self):
        """greenfield 不能被误判：必须显式说允许"""
        self.assertRegex(
            self.text,
            r"greenfield.*may be absent.*do not penalize",
        )

    def test_checklist_has_brownfield_design_completeness_rule(self):
        """Enforce Standards checklist 顶端有 🔴 brownfield 完整性规则，
        并明确"REGRESS to Inventory, not Coding"——这是 brownfield.yaml 的核心差异"""
        self.assertIn("🔴 Brownfield design completeness", self.text)
        self.assertIn("REGRESS to Inventory, not Coding", self.text)

    def test_dedicated_brownfield_regress_example(self):
        """除既有 layering REGRESS 例子外，必须有独立的 brownfield 预飞 REGRESS 例子"""
        # 找 "(brownfield design pre-flight)" 这个例子标题
        self.assertRegex(
            self.text,
            r"Example.*REGRESS.*brownfield.*pre-flight",
        )
        # 例子里点名两节缺失
        idx = self.text.find("brownfield design pre-flight")
        self.assertNotEqual(idx, -1)
        snippet = self.text[idx:idx + 2000]
        self.assertIn("Existing Surface Touched", snippet)
        self.assertIn("Compatibility Risks", snippet)


class Phase4ExistingContractsIntactTestCase(unittest.TestCase):
    """既有 D5 输出契约不能被本步污染"""

    def setUp(self):
        self.text = load_prompt("phase4_review.md")

    def test_review_verdict_contract_intact(self):
        self.assertIn("<review-verdict>PASS</review-verdict>", self.text)
        self.assertIn("<review-findings>", self.text)

    def test_kratos_layering_red_rule_intact(self):
        self.assertIn("🔴 Kratos layering", self.text)


if __name__ == "__main__":
    unittest.main()
