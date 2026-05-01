"""Pipeline DAG schema：YAML → 对象，拓扑序驱动 engine。

V3.1 目标：替换 engine.py 里硬编码的 `_advance_to_phase`，改由 YAML 描述。
D1 只落结构和加载器；D2 engine 改造成 DAG-driven。
"""
from __future__ import annotations

import os
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from pipeline.contracts import CheckpointName, Stage


_DEFAULT_YAML = os.path.join(os.path.dirname(__file__), "default.yaml")

# D6: 内置模板名单，需与 pipeline/dag/<name>.yaml 一一对应。
# 前端 PipelinesPage 下拉硬编码了这 4 个选项，后端 load_template 接到未知名字必须抛错。
# D7: 新增 feature_multi，启用 Phase 4 Review 多视角并行 + 仲裁（实验性，feat flag）。
TEMPLATE_NAMES = ("default", "feature", "bugfix", "refactor", "feature_multi")


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
    """DAG 节点：一个 phase 的配置。

    D7：支持同阶段多角色并行。`prompt_files` 与 `prompt_file` 二选一：
      - `prompt_file` (str)：单 agent 串行执行（D1–D6 行为，默认）。
      - `prompt_files` (dict[role -> prompt_file]) + `aggregator_prompt_file`：
        同阶段 N 个 role 并发跑 agent loop，产物喂给仲裁 agent 合并出最终 verdict。
        目前仅 Phase 4 Review 使用；并行度由 `parallel_workers` 控制（默认 3）。
    """

    stage: Stage
    prompt_file: Optional[str] = None            # agents/phase*.md（单 agent 模式）
    prompt_files: Optional[Dict[str, str]] = None  # {role: prompt_file}（并行模式）
    aggregator_prompt_file: Optional[str] = None  # 并行模式下的仲裁 agent prompt
    parallel_workers: int = 3                     # 并行模式下的最大 worker 数
    depends_on: List[Stage] = Field(default_factory=list)
    checkpoint: Optional[CheckpointName] = None  # 阶段完成后触发的 HITL
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_failure: Optional[OnFailurePolicy] = None

    @model_validator(mode="after")
    def _validate_prompt_mode(self) -> "DAGNode":
        # 二选一：prompt_file xor prompt_files
        has_single = self.prompt_file is not None
        has_multi = self.prompt_files is not None
        if not has_single and not has_multi:
            raise ValueError(
                f"DAG node {self.stage!r} must set either `prompt_file` or `prompt_files`"
            )
        if has_single and has_multi:
            raise ValueError(
                f"DAG node {self.stage!r} cannot set both `prompt_file` and `prompt_files`"
            )
        # 并行模式必须配仲裁 prompt
        if has_multi:
            if not self.prompt_files:
                raise ValueError(
                    f"DAG node {self.stage!r}: `prompt_files` must be non-empty"
                )
            if not self.aggregator_prompt_file:
                raise ValueError(
                    f"DAG node {self.stage!r}: `aggregator_prompt_file` is required "
                    f"when `prompt_files` is set"
                )
            if self.parallel_workers < 1:
                raise ValueError(
                    f"DAG node {self.stage!r}: `parallel_workers` must be >= 1"
                )
        return self

    @property
    def is_parallel(self) -> bool:
        """True 表示本节点走同阶段多 role 并行模式。"""
        return self.prompt_files is not None


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


def load_template(name: str) -> DAG:
    """按模板名加载 DAG YAML（pipeline/dag/<name>.yaml）。未知名字抛 ValueError。"""
    if name not in TEMPLATE_NAMES:
        raise ValueError(f"unknown pipeline template: {name!r}; expected one of {TEMPLATE_NAMES}")
    path = os.path.join(os.path.dirname(__file__), f"{name}.yaml")
    return load_dag(path)
