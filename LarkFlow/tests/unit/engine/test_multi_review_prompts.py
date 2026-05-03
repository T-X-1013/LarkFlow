"""D7 Step 4: 多视角 Review prompt 文件存在性 + 契约兼容性 sanity 检查。

覆盖：
- feature_multi.yaml 引用的 4 份 prompt（3 role + 1 aggregator）文件都真实存在
- 每份 prompt 可被 load_prompt() 加载
- 三份 role prompt 各自声明正确的 lens 关键词（self-identification）
- 三份 role prompt 都包含输出契约 <review-verdict> 标签说明（以供验证 + 防止漂移）
- aggregator prompt 声明"任一 REGRESS ⇒ 全局 REGRESS"的硬规则
- aggregator prompt 保留 <review-verdict> / <review-findings> 标签，与
  engine._parse_review_verdict 正则兼容
"""
from __future__ import annotations

import re
import unittest

from pipeline.core.contracts import Stage
from pipeline.dag.schema import load_template
from pipeline.core.engine import load_prompt


class MultiReviewPromptsTestCase(unittest.TestCase):
    def setUp(self):
        self.dag = load_template("feature_multi")
        self.review_node = self.dag.nodes[Stage.REVIEW]

    def test_feature_multi_references_existing_role_prompts(self):
        for role, prompt_file in self.review_node.prompt_files.items():
            text = load_prompt(prompt_file)
            self.assertTrue(
                text.strip(),
                f"role prompt for {role!r} ({prompt_file}) is empty",
            )

    def test_feature_multi_references_existing_aggregator_prompt(self):
        text = load_prompt(self.review_node.aggregator_prompt_file)
        self.assertTrue(text.strip(), "aggregator prompt is empty")

    def test_role_prompts_declare_lens_and_forbidden_write(self):
        """每份 role prompt 都应声明自己的 lens 名，并明确禁止写文件 / 触发 HITL。"""
        role_to_keyword = {
            "security": "security",
            "testing-coverage": "testing",
            "kratos-layering": "kratos",
        }
        for role, prompt_file in self.review_node.prompt_files.items():
            text = load_prompt(prompt_file).lower()
            self.assertIn(
                role_to_keyword[role],
                text,
                f"{prompt_file} should self-identify with lens keyword {role_to_keyword[role]!r}",
            )
            # 禁止 write / replace（防止并发写冲突）
            self.assertTrue(
                "read-only" in text or "read only" in text,
                f"{prompt_file} must declare READ-ONLY constraint",
            )
            # 禁止 ask_human_approval（子 reviewer 不得触发 HITL）
            self.assertIn(
                "ask_human_approval",
                text,
                f"{prompt_file} must mention ask_human_approval to forbid it",
            )

    def test_role_prompts_specify_verdict_contract(self):
        """Role prompt 必须说明输出 <review-verdict>。"""
        for _, prompt_file in self.review_node.prompt_files.items():
            text = load_prompt(prompt_file)
            self.assertIn("<review-verdict>", text, f"{prompt_file} missing verdict tag spec")
            self.assertIn("PASS", text)
            self.assertIn("REGRESS", text)

    def test_aggregator_prompt_declares_strict_any_regress_rule(self):
        """仲裁 prompt 必须明确"任一 REGRESS ⇒ 全局 REGRESS"规则。"""
        text = load_prompt(self.review_node.aggregator_prompt_file)
        lower = text.lower()
        self.assertTrue(
            any(
                phrase in lower
                for phrase in (
                    "any role regress",
                    "any role returned regress",
                    "global regress",
                )
            ),
            "aggregator prompt must state any-REGRESS-implies-global-REGRESS",
        )
        # failed / cancelled 状态也要强制 REGRESS
        self.assertIn("failed", lower)
        self.assertIn("regress", lower)

    def test_aggregator_output_tags_match_verdict_parser(self):
        """仲裁 prompt 指定的输出格式必须能被 engine._parse_review_verdict 正则吃掉。"""
        text = load_prompt(self.review_node.aggregator_prompt_file)
        # 与 engine._VERDICT_RE / _FINDINGS_RE 对齐
        verdict_re = re.compile(r"<review-verdict>\s*(PASS|REGRESS)\s*</review-verdict>", re.IGNORECASE)
        findings_re = re.compile(r"<review-findings>\s*(.*?)\s*</review-findings>", re.IGNORECASE | re.DOTALL)
        self.assertIsNotNone(
            verdict_re.search(text),
            "aggregator prompt sample must include a verdict tag parsable by _VERDICT_RE",
        )
        self.assertIsNotNone(
            findings_re.search(text),
            "aggregator prompt sample must include a findings tag parsable by _FINDINGS_RE",
        )


if __name__ == "__main__":
    unittest.main()
