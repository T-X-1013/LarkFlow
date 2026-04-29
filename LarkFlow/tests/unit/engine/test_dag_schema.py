"""D5 Step 1: DAG schema 扩展单测。

覆盖：
- OnFailurePolicy 默认值
- DAGNode.on_failure 可选字段 + 从 YAML 解析
- default.yaml review 节点已挂 on_failure（Step 2 依赖）
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from pipeline.contracts import Stage
from pipeline.dag.schema import (
    DAG,
    DAGNode,
    OnFailurePolicy,
    default_dag,
    load_dag,
)


def test_on_failure_policy_defaults():
    policy = OnFailurePolicy()
    assert policy.action == "fail"
    assert policy.to is None
    assert policy.max_attempts == 3


def test_on_failure_policy_regress():
    policy = OnFailurePolicy(action="regress", to=Stage.CODING, max_attempts=2)
    assert policy.action == "regress"
    assert policy.to == Stage.CODING
    assert policy.max_attempts == 2


def test_dag_node_without_on_failure_defaults_to_none():
    node = DAGNode(stage=Stage.DESIGN, prompt_file="phase1_design.md")
    assert node.on_failure is None


def test_load_dag_yaml_with_on_failure(tmp_path: Path):
    yaml_text = textwrap.dedent(
        """
        name: test
        description: test dag with on_failure
        entry: design
        nodes:
          design:
            prompt_file: phase1_design.md
            depends_on: []
          coding:
            prompt_file: phase2_coding.md
            depends_on: [design]
          test:
            prompt_file: phase3_test.md
            depends_on: [coding]
          review:
            prompt_file: phase4_review.md
            depends_on: [test]
            checkpoint: deploy
            on_failure:
              action: regress
              to: coding
              max_attempts: 3
        """
    ).strip()
    p = tmp_path / "dag.yaml"
    p.write_text(yaml_text, encoding="utf-8")

    dag = load_dag(str(p))
    assert isinstance(dag, DAG)
    review = dag.nodes[Stage.REVIEW]
    assert review.on_failure is not None
    assert review.on_failure.action == "regress"
    assert review.on_failure.to == Stage.CODING
    assert review.on_failure.max_attempts == 3

    # 其他节点无 on_failure
    assert dag.nodes[Stage.DESIGN].on_failure is None
    assert dag.nodes[Stage.CODING].on_failure is None
    assert dag.nodes[Stage.TEST].on_failure is None


def test_load_dag_yaml_rejects_unknown_action(tmp_path: Path):
    yaml_text = textwrap.dedent(
        """
        name: bad
        entry: design
        nodes:
          design:
            prompt_file: phase1_design.md
            depends_on: []
            on_failure:
              action: skip
              max_attempts: 1
        """
    ).strip()
    p = tmp_path / "dag.yaml"
    p.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(Exception):  # pydantic ValidationError
        load_dag(str(p))


def test_default_dag_loads_clean():
    """默认 DAG 解析不报错；on_failure 由 Step 2 补上，本用例只确保 schema 扩展向后兼容。"""
    dag = default_dag()
    assert Stage.REVIEW in dag.nodes
