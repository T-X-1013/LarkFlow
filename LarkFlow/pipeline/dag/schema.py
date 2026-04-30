"""Pipeline DAG schema：YAML → 对象，拓扑序驱动 engine。

V3.1 目标：替换 engine.py 里硬编码的 `_advance_to_phase`，改由 YAML 描述。
D1 只落结构和加载器；D2 engine 改造成 DAG-driven。
"""
from __future__ import annotations

import os
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field

from pipeline.contracts import CheckpointName, Stage


_DEFAULT_YAML = os.path.join(os.path.dirname(__file__), "default.yaml")


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff_seconds: float = 0.0


class OnFailurePolicy(BaseModel):
    """阶段结论为不通过时的处理策略。

    目前只用于 Phase 4 Review：当 Agent 输出 `<review-verdict>REGRESS</review-verdict>`
    时，engine 按本策略回退到 `to` 指定阶段并重跑，累计次数达 `max_attempts` 后置 failed。
    """

    action: Literal["fail", "regress"] = "fail"
    to: Optional[Stage] = None
    max_attempts: int = 3


class DAGNode(BaseModel):
    """DAG 节点：一个 phase 的配置。"""

    stage: Stage
    prompt_file: str            # agents/phase*.md
    depends_on: List[Stage] = Field(default_factory=list)
    checkpoint: Optional[CheckpointName] = None  # 阶段完成后触发的 HITL
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_failure: Optional[OnFailurePolicy] = None


class DAG(BaseModel):
    """Pipeline 模板：一组 Stage 节点 + 默认入口。"""

    name: str = "default"
    description: str = ""
    nodes: Dict[Stage, DAGNode]
    entry: Stage

    def topo_order(self) -> List[Stage]:
        """简单拓扑排序；default 模板为线性图，已够用。"""
        visited: Dict[Stage, bool] = {}
        order: List[Stage] = []

        def visit(s: Stage) -> None:
            if visited.get(s):
                return
            visited[s] = True
            node = self.nodes[s]
            for dep in node.depends_on:
                visit(dep)
            order.append(s)

        for stage in self.nodes:
            visit(stage)
        return order

    def next_of(self, stage: Stage) -> Optional[Stage]:
        order = self.topo_order()
        try:
            idx = order.index(stage)
        except ValueError:
            return None
        return order[idx + 1] if idx + 1 < len(order) else None


def load_dag(path: Optional[str] = None) -> DAG:
    """加载 DAG YAML。path 缺省用内置 default.yaml。"""
    target = path or _DEFAULT_YAML
    with open(target, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    nodes_raw = data.get("nodes", {})
    nodes = {
        Stage(k): DAGNode(stage=Stage(k), **v)
        for k, v in nodes_raw.items()
    }
    return DAG(
        name=data.get("name", "default"),
        description=data.get("description", ""),
        nodes=nodes,
        entry=Stage(data.get("entry", "design")),
    )


def default_dag() -> DAG:
    return load_dag()
