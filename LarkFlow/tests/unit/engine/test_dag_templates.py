"""D6 Step 2: Pipeline 模板 3 套的 schema 加载与差异化断言。

覆盖：
- load_template 对每个模板名都能解析成合法 DAG
- 未知模板名抛 ValueError
- 各模板关键差异字段（on_failure.max_attempts / review.checkpoint）符合预期
"""
from __future__ import annotations

import pytest

from pipeline.core.contracts import CheckpointName, Stage
from pipeline.dag.schema import TEMPLATE_NAMES, load_template


def test_all_templates_load_clean():
    for name in TEMPLATE_NAMES:
        dag = load_template(name)
        # 四个 stage 都在
        for s in (Stage.DESIGN, Stage.CODING, Stage.TEST, Stage.REVIEW):
            assert s in dag.nodes, f"{name}.yaml 缺少 stage {s}"
        # design 必挂 HITL
        assert dag.nodes[Stage.DESIGN].checkpoint == CheckpointName.DESIGN


def test_unknown_template_raises():
    with pytest.raises(ValueError):
        load_template("not-a-template")


def test_bugfix_allows_more_regression_attempts():
    dag = load_template("bugfix")
    policy = dag.nodes[Stage.REVIEW].on_failure
    assert policy is not None
    assert policy.max_attempts == 5
    assert policy.action == "regress"
    assert policy.to == Stage.CODING


def test_feature_matches_default_retry_budget():
    feature = load_template("feature")
    default = load_template("default")
    assert (
        feature.nodes[Stage.REVIEW].on_failure.max_attempts
        == default.nodes[Stage.REVIEW].on_failure.max_attempts
    )


def test_refactor_drops_deploy_checkpoint():
    dag = load_template("refactor")
    # refactor 模板 review 节点不应挂 deploy checkpoint：跳过第 2 HITL
    assert dag.nodes[Stage.REVIEW].checkpoint is None
    # 但 design HITL 仍然保留
    assert dag.nodes[Stage.DESIGN].checkpoint == CheckpointName.DESIGN
    # 重构回归上限比 default 严格
    assert dag.nodes[Stage.REVIEW].on_failure.max_attempts == 2
