"""D7: 子 session 机制（Phase 4 多视角并行 Review 的地基）。

主 session 与 sub session 共享 `SqliteSessionStore`，但通过不同 key 隔离：
  - 主 session key = demand_id
  - 子 session key = f"{demand_id}::review::{role}"

每个 role worker 跑独立的 agent loop，history / metrics / client 全部独立，
执行完毕后由主线程把 tokens / duration 合并回主 session["metrics"]
（含 `by_role` 维度），子 session 自身保留在 store 里作为历史留档。

本模块**纯函数 + store 注入**，不依赖 engine.py 的模块级 STORE；
engine.py 在调用点显式传入 STORE，便于单测直接替换 mock store。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pipeline.persistence import SessionStore

# 子 session key 分隔符。`::` 在 sqlite key / 日志 / grep 里都安全，
# 且不会与 demand_id（业务上是 Base 自增编号或类似字符串）撞车。
SUBSESSION_ROLE_SEP = "::review::"


def subsession_key(parent_demand_id: str, role: str) -> str:
    """生成子 session 的存储 key。

    @params:
        parent_demand_id: 主 session 的 demand_id
        role: role 名（例如 "security" / "testing-coverage" / "kratos-layering"）

    @return:
        拼接后的子 session key
    """
    if not parent_demand_id:
        raise ValueError("parent_demand_id is required")
    if not role or not role.strip():
        raise ValueError("role is required")
    if SUBSESSION_ROLE_SEP in role or "::" in role:
        # 避免 role 里含分隔符导致 parse_subsession_key 歧义
        raise ValueError(f"role must not contain '::' (got {role!r})")
    return f"{parent_demand_id}{SUBSESSION_ROLE_SEP}{role}"


def is_subsession_key(key: str) -> bool:
    """True 表示是子 session key；用于调用方过滤 list_active 等结果。"""
    return SUBSESSION_ROLE_SEP in (key or "")


def parse_subsession_key(key: str) -> Optional[tuple]:
    """解包子 session key 为 (parent_demand_id, role)；不是子 key 返回 None。"""
    if not is_subsession_key(key):
        return None
    parent, _, role = key.partition(SUBSESSION_ROLE_SEP)
    return parent, role


def init_subsession(parent_session: Dict[str, Any], role: str) -> Dict[str, Any]:
    """基于主 session 的只读上下文，构造一份全新的 sub session。

    继承：`demand_id`（重写为子 key）、`parent_demand_id`、`role`、`provider`、
    `target_dir`、`workspace_root`。
    新开：`history=[]`、`metrics` 独立零值、`pending_approval=None`、
    `hitl_disabled=True`（子 reviewer 不允许触发第 1/2 HITL）。
    `phase` 固定为 "reviewing"。

    transient 字段（client / logger）**不在这里构造**，由调用方（engine.py）
    在 save/load 后按需重建，避免本模块依赖 LLM / 日志层。
    """
    parent_demand_id = parent_session.get("demand_id")
    if not parent_demand_id:
        raise ValueError("parent_session missing 'demand_id'")
    provider = parent_session.get("provider")
    if not provider:
        raise ValueError("parent_session missing 'provider'")

    sub: Dict[str, Any] = {
        # 继承的只读上下文
        "demand_id": subsession_key(parent_demand_id, role),
        "parent_demand_id": parent_demand_id,
        "role": role,
        "provider": provider,
        "target_dir": parent_session.get("target_dir"),
        "workspace_root": parent_session.get("workspace_root"),
        # 独立运行时状态
        "phase": "reviewing",
        "history": [],
        "metrics": {"tokens_input": 0, "tokens_output": 0},
        # 第 1/2 HITL 都在主 session 推进，子 reviewer 不得触发
        "pending_approval": None,
        "hitl_disabled": True,
    }
    return sub


def save_subsession(
    store: SessionStore,
    parent_demand_id: str,
    role: str,
    session: Dict[str, Any],
) -> None:
    """把 sub session 写回 store，key 自动展开为子 key。"""
    key = subsession_key(parent_demand_id, role)
    store.save(key, session)


def load_subsession(
    store: SessionStore,
    parent_demand_id: str,
    role: str,
) -> Optional[Dict[str, Any]]:
    """按 (parent_demand_id, role) 读取 sub session；不存在返回 None。"""
    key = subsession_key(parent_demand_id, role)
    return store.get(key)


def finalize_subsession(
    store: SessionStore,
    parent_demand_id: str,
    role: str,
    session: Dict[str, Any],
    *,
    terminal_phase: str = "done",
) -> None:
    """把 sub session 标记为终态并落盘，确保 `list_active` 不再返回它。

    子 session 作为历史留档保留（不删除），方便回看 role-level history。
    """
    session["phase"] = terminal_phase
    save_subsession(store, parent_demand_id, role, session)


def merge_subsession_metrics(
    parent_session: Dict[str, Any],
    sub_session: Dict[str, Any],
    role: str,
    *,
    duration_ms: int = 0,
) -> None:
    """把子 session 的 tokens 合并回主 session，并在 metrics.by_role 下单列记录。

    合并语义：
      - 主 session.metrics.tokens_input/output += 子 session 对应值
      - 主 session.metrics.by_role[role] = {tokens_input, tokens_output, duration_ms}

    duration_ms 由主线程测得（wall-clock），不来自子 session，因为子 session 自身
    不维护 duration 字段；主线程在提交 future 前后打点即可。
    """
    sub_metrics = sub_session.get("metrics") or {}
    sub_in = int(sub_metrics.get("tokens_input", 0) or 0)
    sub_out = int(sub_metrics.get("tokens_output", 0) or 0)

    parent_metrics = parent_session.setdefault(
        "metrics", {"tokens_input": 0, "tokens_output": 0}
    )
    parent_metrics["tokens_input"] = (
        int(parent_metrics.get("tokens_input", 0) or 0) + sub_in
    )
    parent_metrics["tokens_output"] = (
        int(parent_metrics.get("tokens_output", 0) or 0) + sub_out
    )

    by_role = parent_metrics.setdefault("by_role", {})
    by_role[role] = {
        "tokens_input": sub_in,
        "tokens_output": sub_out,
        "duration_ms": int(duration_ms or 0),
    }
