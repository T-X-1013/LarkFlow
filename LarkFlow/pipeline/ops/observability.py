"""结构化日志与指标

为每个需求提供带 demand_id / phase 上下文的 JSON logger，输出到 stdout 与
logs/larkflow.jsonl。配合 B6 暴露的 AgentTurn.usage，支持 token 与延迟埋点，
并统计到 session["metrics"] 以供 A1 持久化后用 jq 聚合。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, Mapping, Optional

from pipeline.config import runtime as runtime_config
from pipeline.core.contracts import MetricsItem, PipelineState, RoleMetrics, TokenUsage

_LOGGER_NAME = "larkflow"

# 这里列的是允许写入结构化 JSON 的标准 extra 字段。
# 统一白名单可以避免调用方临时塞入任意字段，把日志 schema 打散。
_STD_EXTRA_KEYS = (
    "demand_id",
    "phase",
    "event",
    "tool_name",
    "provider",
    "model",
    "reason",
    "attempt",
    "max_retries",
    "wait_seconds",
    "finished",
    "tool_call_count",
    "tokens_input",
    "tokens_output",
    "duration_ms",
    "tokens_in",
    "tokens_out",
    "total_tokens",
    "latency_ms",
    # D7：Phase 4 多视角并行新增字段，用于按 role 区分三路 reviewer
    "role",
    "parent_demand_id",
)
_configured = False


class _JsonFormatter(logging.Formatter):
    """把 LoggerAdapter 的 extra 字段稳定序列化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        """
        把标准 logging record 转换为统一 JSON 字符串。

        @params:
            record: Python logging 产生的原始日志记录

        @return:
            返回单行 JSON 字符串，便于 stdout、文件和 Loki 统一采集
        """
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key in _STD_EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _DemandLoggerAdapter(logging.LoggerAdapter):
    """保证 adapter 自带的 demand_id 等字段与调用点 extra 合并，而非被覆盖。"""

    def process(self, msg, kwargs):
        """
        合并 adapter 默认 extra 与调用方临时 extra。

        @params:
            msg: 原始日志消息
            kwargs: logging 调用时传入的关键字参数

        @return:
            返回 logging.LoggerAdapter 约定的 `(msg, kwargs)` 元组
        """
        caller_extra = kwargs.get("extra") or {}
        merged = {**(self.extra or {}), **caller_extra}
        kwargs["extra"] = merged
        return msg, kwargs


def _configure() -> None:
    """
    初始化 LarkFlow 全局结构化 logger。

    @params:
        无

    @return:
        无返回值；首次调用时配置 stdout 与文件双写 handler
    """
    global _configured
    if _configured:
        return

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(runtime_config.log_level())
    logger.propagate = False

    formatter = _JsonFormatter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_path = runtime_config.log_file()
    log_dir = os.path.dirname(os.path.abspath(log_path)) or "."
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _configured = True


def get_logger(
    demand_id: str,
    phase: Optional[str] = None,
    role: Optional[str] = None,
    parent_demand_id: Optional[str] = None,
) -> _DemandLoggerAdapter:
    """
    为指定需求返回带上下文字段的结构化 logger。

    @params:
        demand_id: 当前需求 ID（子 session 传子 key）
        phase: 可选阶段名；传入后会作为默认 phase 写入每条日志
        role: D7 多视角并行 Review 的 role 名（security / testing-coverage /
            kratos-layering）；非子 reviewer 时留空
        parent_demand_id: D7 子 session 的父 demand_id；用于 Grafana/Loki 按父
            pipeline 聚合 metrics

    @return:
        返回 LoggerAdapter，自动附带 demand_id 与可选 phase/role/parent
    """
    _configure()
    extra: Dict[str, Any] = {"demand_id": demand_id}
    if phase is not None:
        extra["phase"] = phase
    if role is not None:
        extra["role"] = role
    if parent_demand_id is not None:
        extra["parent_demand_id"] = parent_demand_id
    return _DemandLoggerAdapter(logging.getLogger(_LOGGER_NAME), extra)


def log_turn_metrics(
    logger: logging.LoggerAdapter,
    phase: Optional[str],
    usage: Mapping[str, Any],
    tool_name: Optional[str] = None,
    *,
    role: Optional[str] = None,
) -> None:
    """
    把一轮 Agent 交互的 usage 指标打成结构化事件。

    @params:
        logger: 带 demand_id 上下文的结构化 logger
        phase: 当前阶段名
        usage: 归一后的 usage 字段
        tool_name: 可选工具名；当本轮由工具调用触发时用于补充上下文
        role: D7 子 reviewer 的 role 名；非空时写入 extra.role 供 Grafana
            按 role 维度拆图

    @return:
        无返回值；直接输出结构化日志
    """
    extra: Dict[str, Any] = {
        "event": "agent_turn",
        "phase": phase,
        "tool_name": tool_name,
        "tokens_input": int(usage.get("prompt_tokens") or 0),
        "tokens_output": int(usage.get("completion_tokens") or 0),
        "duration_ms": int(usage.get("latency_ms") or 0),
        "tokens_in": int(usage.get("prompt_tokens") or 0),
        "tokens_out": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "latency_ms": int(usage.get("latency_ms") or 0),
    }
    if role is not None:
        extra["role"] = role
    logger.info("agent_turn", extra=extra)


def log_llm_call_started(
    logger: logging.LoggerAdapter,
    phase: Optional[str],
    provider: str,
    model: str,
) -> None:
    """
    记录一轮 LLM 调用开始事件。

    @params:
        logger: 带 demand_id 上下文的结构化 logger
        phase: 当前阶段名
        provider: 模型提供方，例如 openai、anthropic
        model: 实际调用的模型名

    @return:
        无返回值；直接输出结构化日志
    """
    logger.info(
        "llm_call_start",
        extra={
            "event": "llm_call_start",
            "phase": phase,
            "provider": provider,
            "model": model,
        },
    )


def log_llm_call_finished(
    logger: logging.LoggerAdapter,
    phase: Optional[str],
    provider: str,
    model: str,
    usage: Mapping[str, Any],
    *,
    finished: bool,
    tool_call_count: int,
) -> None:
    """
    记录一轮 LLM 调用完成事件。

    @params:
        logger: 带 demand_id 上下文的结构化 logger
        phase: 当前阶段名
        provider: 模型提供方
        model: 实际调用的模型名
        usage: 统一归一后的 usage 字段
        finished: 本轮是否已经结束，不再要求继续调用工具
        tool_call_count: 本轮产生的工具调用数

    @return:
        无返回值；直接输出结构化日志
    """
    # tokens_input / tokens_output / duration_ms 是新的更直观字段；
    # tokens_in / tokens_out / latency_ms 继续保留，用于兼容已有日志查询和聚合脚本。
    logger.info(
        "llm_call_end",
        extra={
            "event": "llm_call_end",
            "phase": phase,
            "provider": provider,
            "model": model,
            "tokens_input": int(usage.get("prompt_tokens") or 0),
            "tokens_output": int(usage.get("completion_tokens") or 0),
            "duration_ms": int(usage.get("latency_ms") or 0),
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "latency_ms": int(usage.get("latency_ms") or 0),
            "finished": finished,
            "tool_call_count": tool_call_count,
        },
    )


def log_llm_retry(
    logger: logging.LoggerAdapter,
    phase: Optional[str],
    provider: str,
    model: str,
    reason: str,
    *,
    attempt: int,
    max_retries: int,
    wait_seconds: float,
) -> None:
    """
    记录一条 LLM 重试事件。

    @params:
        logger: 带 demand_id 上下文的结构化 logger
        phase: 当前阶段名
        provider: 模型提供方
        model: 实际调用的模型名
        reason: 触发重试的原因描述
        attempt: 当前是第几次尝试，按 1 开始计数
        max_retries: 最大重试次数
        wait_seconds: 本次退避等待秒数

    @return:
        无返回值；直接输出结构化日志
    """
    logger.warning(
        "llm_retry",
        extra={
            "event": "llm_retry",
            "phase": phase,
            "provider": provider,
            "model": model,
            "reason": reason,
            "attempt": attempt,
            "max_retries": max_retries,
            "wait_seconds": round(wait_seconds, 3),
        },
    )


def accumulate_metrics(session: Dict[str, Any], usage: Mapping[str, Any]) -> None:
    """
    把单轮 usage 累加到 session['metrics']。

    @params:
        session: 当前需求的会话状态字典
        usage: 单轮模型调用的归一化 usage 数据

    @return:
        无返回值；直接在 session 上原地更新 metrics 聚合结果
    """
    metric_defaults = {
        "turns": 0,
        # 新字段更贴近产品和可观测性面板语义。
        "tokens_input": 0,
        "tokens_output": 0,
        # 旧字段继续保留，避免打断已有统计脚本和历史 session 结构。
        "tokens_in": 0,
        "tokens_out": 0,
        "total_tokens": 0,
        "duration_ms": 0,
        "latency_ms": 0,
    }
    metrics = session.setdefault("metrics", {})
    for key, default in metric_defaults.items():
        metrics.setdefault(key, default)
    metrics["turns"] += 1
    metrics["tokens_input"] += int(usage.get("prompt_tokens") or 0)
    metrics["tokens_output"] += int(usage.get("completion_tokens") or 0)
    metrics["tokens_in"] += int(usage.get("prompt_tokens") or 0)
    metrics["tokens_out"] += int(usage.get("completion_tokens") or 0)
    metrics["total_tokens"] += int(usage.get("total_tokens") or 0)
    metrics["duration_ms"] += int(usage.get("latency_ms") or 0)
    metrics["latency_ms"] += int(usage.get("latency_ms") or 0)


def _coerce_int(value: Any) -> int:
    """
    把任意输入尽量转成非负整数。

    @params:
        value: 待转换的输入值

    @return:
        成功时返回非负整数；失败时返回 0
    """
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _read_metric(metrics: Mapping[str, Any], *names: str) -> int:
    """
    按顺序读取聚合指标字段，兼容新旧 key。

    @params:
        metrics: session["metrics"] 字典
        names: 候选字段名列表

    @return:
        返回第一个成功解析到的非负整数；全都缺失时返回 0
    """
    for name in names:
        if name in metrics:
            return _coerce_int(metrics.get(name))
    return 0


def build_metrics_item(
    pipeline_id: str,
    state: PipelineState,
    session: Optional[Mapping[str, Any]],
) -> MetricsItem:
    """
    从 PipelineState + session 快照构造 `/metrics/pipelines` 响应项。

    @params:
        pipeline_id: pipeline ID
        state: 由 engine_control.build_state 反射出的运行态
        session: 原始 session 快照，可为空

    @return:
        返回填充好 tokens / duration / stages 的 MetricsItem
    """
    metrics = (session or {}).get("metrics") or {}
    # D7：feature_multi 模板把 session["metrics"]["by_role"] 聚合为 dict
    # {role: {tokens_input, tokens_output, duration_ms}}，这里把它摊平成
    # List[RoleMetrics] 让前端按数组渲染。非并行模板该字段为空列表。
    raw_by_role = metrics.get("by_role") or {}
    by_role: list = []
    if isinstance(raw_by_role, dict):
        for role_name, entry in raw_by_role.items():
            if not isinstance(entry, dict):
                continue
            try:
                by_role.append(RoleMetrics(
                    role=str(role_name),
                    tokens_input=_coerce_int(entry.get("tokens_input")),
                    tokens_output=_coerce_int(entry.get("tokens_output")),
                    duration_ms=_coerce_int(entry.get("duration_ms")),
                ))
            except Exception:  # noqa: BLE001 — 损坏条目不阻塞 metrics API
                continue
    return MetricsItem(
        pipeline_id=pipeline_id,
        status=state.status,
        duration_ms=_read_metric(metrics, "duration_ms", "latency_ms"),
        tokens=TokenUsage(
            input=_read_metric(metrics, "tokens_input", "tokens_in"),
            output=_read_metric(metrics, "tokens_output", "tokens_out"),
        ),
        stages=state.stages,
        by_role=by_role,
    )
