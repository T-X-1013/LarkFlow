"""Step 4 sanity 检查：brownfield 模板加载、拓扑和回归策略。

这里不验证 engine 是否能跑 Inventory 节点（那是后续步骤的事），只钉住：
1. `load_template("brownfield")` 能解析成功，pydantic 校验通过；
2. 节点拓扑序是 inventory → design → coding → test → review，与
   feature.yaml 的 4 阶段相比多一个前置；
3. Review 阶段的 on_failure.regress.to 指向 INVENTORY，不是 CODING——
   brownfield 模板的核心差异在这里，写错就失去意义。
"""
from __future__ import annotations

import unittest

from pipeline.core.contracts import CheckpointName, Stage
from pipeline.dag.schema import TEMPLATE_NAMES, load_template


class BrownfieldTemplateTestCase(unittest.TestCase):
    def setUp(self):
        self.dag = load_template("brownfield")

    def test_brownfield_is_registered(self):
        self.assertIn("brownfield", TEMPLATE_NAMES)
        self.assertEqual(self.dag.name, "brownfield")

    def test_entry_is_inventory(self):
        self.assertEqual(self.dag.entry, Stage.INVENTORY)

    def test_topo_order_starts_with_inventory(self):
        order = self.dag.topo_order()
        self.assertEqual(
            order,
            [Stage.INVENTORY, Stage.DESIGN, Stage.CODING, Stage.TEST, Stage.REVIEW],
        )

    def test_inventory_node_uses_phase0_prompt(self):
        node = self.dag.nodes[Stage.INVENTORY]
        self.assertEqual(node.prompt_file, "phase0_inventory.md")
        self.assertEqual(node.depends_on, [])
        self.assertIsNone(node.checkpoint)

    def test_design_depends_on_inventory(self):
        node = self.dag.nodes[Stage.DESIGN]
        self.assertEqual(node.depends_on, [Stage.INVENTORY])
        self.assertEqual(node.checkpoint, CheckpointName.DESIGN)

    def test_review_regresses_to_inventory_not_coding(self):
        """brownfield 模板的核心差异：回归到 inventory。回 coding 等于没改。"""
        review = self.dag.nodes[Stage.REVIEW]
        self.assertIsNotNone(review.on_failure)
        self.assertEqual(review.on_failure.action, "regress")
        self.assertEqual(review.on_failure.to, Stage.INVENTORY)
        self.assertEqual(review.on_failure.max_attempts, 3)

    def test_review_keeps_deploy_checkpoint(self):
        review = self.dag.nodes[Stage.REVIEW]
        self.assertEqual(review.checkpoint, CheckpointName.DEPLOY)

    def test_next_of_walks_through_inventory(self):
        self.assertEqual(self.dag.next_of(Stage.INVENTORY), Stage.DESIGN)
        self.assertEqual(self.dag.next_of(Stage.DESIGN), Stage.CODING)
        self.assertIsNone(self.dag.next_of(Stage.REVIEW))


class FeatureTemplateUnaffectedTestCase(unittest.TestCase):
    """0-1 模板不能被 brownfield 改动污染：feature 仍然 4 阶段、回归到 coding。"""

    def test_feature_still_starts_at_design(self):
        dag = load_template("feature")
        self.assertEqual(dag.entry, Stage.DESIGN)
        self.assertEqual(
            dag.topo_order(),
            [Stage.DESIGN, Stage.CODING, Stage.TEST, Stage.REVIEW],
        )

    def test_feature_review_still_regresses_to_coding(self):
        dag = load_template("feature")
        review = dag.nodes[Stage.REVIEW]
        self.assertEqual(review.on_failure.to, Stage.CODING)


if __name__ == "__main__":
    unittest.main()
