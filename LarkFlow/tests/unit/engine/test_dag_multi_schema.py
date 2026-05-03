"""D7 Step 1: DAG schema 多 role 并行扩展单测。

覆盖：
- DAGNode 单/多 prompt 二选一互斥校验
- 并行模式下 aggregator_prompt_file 必填
- parallel_workers 下限校验
- feature_multi.yaml 能被解析，review 节点三路 role + 仲裁 prompt 齐备
- is_parallel 属性读出正确
- TEMPLATE_NAMES 白名单包含 feature_multi
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pipeline.core.contracts import CheckpointName, Stage
from pipeline.dag.schema import (
    DAGNode,
    TEMPLATE_NAMES,
    load_dag,
    load_template,
)


def test_dagnode_single_prompt_is_default_non_parallel():
    node = DAGNode(stage=Stage.REVIEW, prompt_file="phase4_review.md")
    assert node.is_parallel is False
    assert node.prompt_files is None
    assert node.aggregator_prompt_file is None


def test_dagnode_multi_prompt_requires_aggregator():
    with pytest.raises(Exception):  # pydantic ValidationError
        DAGNode(
            stage=Stage.REVIEW,
            prompt_files={"security": "phase4_review_security.md"},
        )


def test_dagnode_multi_prompt_with_aggregator_ok():
    node = DAGNode(
        stage=Stage.REVIEW,
        prompt_files={
            "security": "phase4_review_security.md",
            "testing-coverage": "phase4_review_testing.md",
            "kratos-layering": "phase4_review_kratos.md",
        },
        aggregator_prompt_file="phase4_aggregator.md",
        parallel_workers=3,
    )
    assert node.is_parallel is True
    assert len(node.prompt_files) == 3
    assert node.parallel_workers == 3


def test_dagnode_rejects_both_single_and_multi():
    with pytest.raises(Exception):  # pydantic ValidationError
        DAGNode(
            stage=Stage.REVIEW,
            prompt_file="phase4_review.md",
            prompt_files={"security": "x.md"},
            aggregator_prompt_file="phase4_aggregator.md",
        )


def test_dagnode_rejects_neither_single_nor_multi():
    with pytest.raises(Exception):  # pydantic ValidationError
        DAGNode(stage=Stage.REVIEW)


def test_dagnode_rejects_empty_prompt_files():
    with pytest.raises(Exception):
        DAGNode(
            stage=Stage.REVIEW,
            prompt_files={},
            aggregator_prompt_file="phase4_aggregator.md",
        )


def test_dagnode_rejects_zero_parallel_workers():
    with pytest.raises(Exception):
        DAGNode(
            stage=Stage.REVIEW,
            prompt_files={"security": "x.md"},
            aggregator_prompt_file="phase4_aggregator.md",
            parallel_workers=0,
        )


def test_template_names_includes_feature_multi():
    assert "feature_multi" in TEMPLATE_NAMES


def test_feature_multi_template_loads_with_parallel_review():
    dag = load_template("feature_multi")
    # 四阶段齐全
    for s in (Stage.DESIGN, Stage.CODING, Stage.TEST, Stage.REVIEW):
        assert s in dag.nodes
    # 前三阶段仍走单 agent 单 prompt
    for s in (Stage.DESIGN, Stage.CODING, Stage.TEST):
        assert dag.nodes[s].is_parallel is False
        assert dag.nodes[s].prompt_file is not None
    # Review 走并行
    review = dag.nodes[Stage.REVIEW]
    assert review.is_parallel is True
    assert review.prompt_file is None
    assert review.parallel_workers == 3
    assert set(review.prompt_files.keys()) == {
        "security",
        "testing-coverage",
        "kratos-layering",
    }
    assert review.aggregator_prompt_file == "phase4_aggregator.md"
    # 两个 HITL 与回归策略与 default/feature 对齐
    assert dag.nodes[Stage.DESIGN].checkpoint == CheckpointName.DESIGN
    assert review.checkpoint == CheckpointName.DEPLOY
    assert review.on_failure is not None
    assert review.on_failure.action == "regress"
    assert review.on_failure.to == Stage.CODING
    assert review.on_failure.max_attempts == 3


def test_load_dag_parallel_yaml_roundtrip(tmp_path: Path):
    yaml_text = textwrap.dedent(
        """
        name: t
        entry: design
        nodes:
          design: {prompt_file: phase1_design.md, depends_on: []}
          coding: {prompt_file: phase2_coding.md, depends_on: [design]}
          test:   {prompt_file: phase3_test.md,   depends_on: [coding]}
          review:
            depends_on: [test]
            parallel_workers: 2
            prompt_files:
              a: a.md
              b: b.md
            aggregator_prompt_file: agg.md
        """
    ).strip()
    p = tmp_path / "dag.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    dag = load_dag(str(p))
    review = dag.nodes[Stage.REVIEW]
    assert review.is_parallel is True
    assert review.parallel_workers == 2
    assert review.prompt_files == {"a": "a.md", "b": "b.md"}
    assert review.aggregator_prompt_file == "agg.md"


def test_default_and_other_templates_unchanged():
    """确保 D7 schema 扩展对既有四模板零影响（向后兼容核心断言）。"""
    for name in ("default", "feature", "bugfix", "refactor"):
        dag = load_template(name)
        for s in (Stage.DESIGN, Stage.CODING, Stage.TEST, Stage.REVIEW):
            node = dag.nodes[s]
            assert node.is_parallel is False, f"{name}.{s} 不应为并行"
            assert node.prompt_file is not None, f"{name}.{s} 应有单 prompt_file"
