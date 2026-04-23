"""结构化日志与指标 (A4)

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

_LOGGER_NAME = "larkflow"
_STD_EXTRA_KEYS = (
    "demand_id",
    "phase",
    "event",
    "tool_name",
    "tokens_in",
    "tokens_out",
    "total_tokens",
    "latency_ms",
)
_configured = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
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
        caller_extra = kwargs.get("extra") or {}
        merged = {**(self.extra or {}), **caller_extra}
        kwargs["extra"] = merged
        return msg, kwargs


def _configure() -> None:
    global _configured
    if _configured:
        return

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(os.getenv("LARKFLOW_LOG_LEVEL", "INFO").upper())
    logger.propagate = False

    formatter = _JsonFormatter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_path = os.getenv("LARKFLOW_LOG_FILE", "logs/larkflow.jsonl")
    log_dir = os.path.dirname(os.path.abspath(log_path)) or "."
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _configured = True


def get_logger(demand_id: str, phase: Optional[str] = None) -> _DemandLoggerAdapter:
    """为指定需求返回带上下文字段的结构化 logger。"""
    _configure()
    extra: Dict[str, Any] = {"demand_id": demand_id}
    if phase is not None:
        extra["phase"] = phase
    return _DemandLoggerAdapter(logging.getLogger(_LOGGER_NAME), extra)


def log_turn_metrics(
    logger: logging.LoggerAdapter,
    phase: Optional[str],
    usage: Mapping[str, Any],
    tool_name: Optional[str] = None,
) -> None:
    """把一轮 agent turn 的 usage 指标打成结构化事件。"""
    logger.info(
        "agent_turn",
        extra={
            "event": "agent_turn",
            "phase": phase,
            "tool_name": tool_name,
            "tokens_in": int(usage.get("prompt_tokens") or 0),
            "tokens_out": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "latency_ms": int(usage.get("latency_ms") or 0),
        },
    )


def accumulate_metrics(session: Dict[str, Any], usage: Mapping[str, Any]) -> None:
    """把单轮 usage 累加到 session['metrics']，方便从持久化 payload 里聚合。"""
    metrics = session.setdefault(
        "metrics",
        {"turns": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "latency_ms": 0},
    )
    metrics["turns"] += 1
    metrics["tokens_in"] += int(usage.get("prompt_tokens") or 0)
    metrics["tokens_out"] += int(usage.get("completion_tokens") or 0)
    metrics["total_tokens"] += int(usage.get("total_tokens") or 0)
    metrics["latency_ms"] += int(usage.get("latency_ms") or 0)
