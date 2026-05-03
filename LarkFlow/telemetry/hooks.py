"""LarkFlow 业务埋点 hook 层。

本文件的目标是把“埋点命名、attributes 组织方式、运行时初始化细节”集中起来，
从而让 ``engine.py``、``lark_interaction.py`` 等业务文件只保留薄薄一层调用。

分层约定：
- ``telemetry/otel.py``：OTEL SDK 级实现；
- ``telemetry/hooks.py``：业务语义级封装；
- ``pipeline/otel*.py``：兼容旧导入路径的转发壳。
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from telemetry.otel import init_otel, shutdown_otel, start_span

_shutdown_registered = False


def setup_runtime_otel(default_service_name: str = "larkflow") -> None:
    """初始化运行时 OTEL，并在首次成功启用后注册退出清理钩子。"""
    global _shutdown_registered

    if not init_otel(default_service_name):
        return
    if _shutdown_registered:
        return
    atexit.register(shutdown_otel)
    _shutdown_registered = True


@contextmanager
def trace_lark_start_request(demand_id: str, doc_url: str) -> Iterator[Any]:
    """飞书启动请求入口 span。"""
    with start_span(
        "lark.start_request",
        {
            "demand_id": demand_id,
            "doc_url": doc_url,
        },
    ) as span:
        yield span


@contextmanager
def trace_lark_card_action(
    event_id: str,
    demand_id: Optional[str],
    action_type: Optional[str],
) -> Iterator[Any]:
    """飞书卡片点击动作 span。"""
    with start_span(
        "lark.card_action",
        {
            "event_id": event_id,
            "demand_id": demand_id,
            "action_type": action_type,
        },
    ) as span:
        yield span


@contextmanager
def trace_bitable_record_changed(event_id: str) -> Iterator[Any]:
    """多维表格记录变更事件 span。"""
    with start_span(
        "lark.bitable_record_changed",
        {
            "event_id": event_id,
        },
    ) as span:
        yield span


@contextmanager
def trace_phase_execution(
    demand_id: str,
    phase: str,
    prompt_file: Optional[str],
    role: Optional[str] = None,
) -> Iterator[Any]:
    """单个 phase 执行 span。

    D7：role 非空时写入 span attribute，用于在 Tempo / Grafana 中按
    role 分色（security / testing-coverage / kratos-layering）。
    """
    attrs: dict = {
        "demand_id": demand_id,
        "phase": phase,
        "prompt_file": prompt_file,
    }
    if role is not None:
        attrs["role"] = role
    with start_span(f"phase.{phase}", attrs) as span:
        yield span


@contextmanager
def trace_demand_start(demand_id: str, phase: str) -> Iterator[Any]:
    """新需求启动总入口 span。"""
    with start_span(
        "pipeline.start_new_demand",
        {
            "demand_id": demand_id,
            "phase": phase,
        },
    ) as span:
        yield span


@contextmanager
def trace_phase_resume(demand_id: str, phase: str) -> Iterator[Any]:
    """断点恢复某个 phase 的 span。"""
    with start_span(
        "pipeline.resume_from_phase",
        {
            "demand_id": demand_id,
            "phase": phase,
        },
    ) as span:
        yield span


@contextmanager
def trace_approval_resume(demand_id: str, approved: bool) -> Iterator[Any]:
    """审批回调恢复流程的 span。"""
    with start_span(
        "pipeline.resume_after_approval",
        {
            "demand_id": demand_id,
            "approved": approved,
        },
    ) as span:
        yield span


@contextmanager
def trace_deploy_phase(demand_id: str, phase: str) -> Iterator[Any]:
    """部署阶段 span。"""
    with start_span(
        "phase.deploying",
        {
            "demand_id": demand_id,
            "phase": phase,
        },
    ) as span:
        yield span
