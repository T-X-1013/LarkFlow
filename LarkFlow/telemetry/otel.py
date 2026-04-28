"""LarkFlow 的 OpenTelemetry 核心实现。

设计目标保持“最小侵入”：
1. 当未设置 ``OTEL_EXPORTER_OTLP_ENDPOINT`` 时，整体退化为 no-op，不影响原有业务流程；
2. 依赖按需懒加载，避免本地尚未安装 OTEL 依赖时直接导入失败；
3. 仅暴露少量稳定接口，供业务层通过 ``telemetry/hooks.py`` 间接使用。

文件职责：
- 本文件负责 OTEL SDK 初始化、Exporter 配置、Tracer 获取与手工 span 上下文；
- 不直接承载具体业务语义，业务埋点命名与 attributes 组装放在 ``telemetry/hooks.py``。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

_trace_api = None
_provider = None
_shutdown = None
_enabled = False
_service_name = "larkflow"


class _NoopSpan:
    """OTEL 未启用时返回的占位 span。

    这样业务代码可以始终调用 ``set_attribute`` / ``record_exception``，
    而不必在调用处判断当前是否启用了 OTEL。
    """

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None


def _normalize_otlp_endpoint(raw: str) -> str:
    """把带协议头的 OTLP endpoint 归一化为 gRPC exporter 需要的 host:port 形式。"""
    endpoint = (raw or "").strip()
    if endpoint.startswith("http://"):
        return endpoint[len("http://") :]
    if endpoint.startswith("https://"):
        return endpoint[len("https://") :]
    return endpoint


def init_otel(default_service_name: str = "larkflow") -> bool:
    """按环境变量初始化 OTEL。

    返回值语义：
    - ``True``：已启用 OTEL，后续可以正常创建真实 span；
    - ``False``：当前保持 no-op（常见原因是未配置 endpoint，或本机未安装 OTEL 依赖）。
    """
    global _trace_api, _provider, _shutdown, _enabled, _service_name

    if _enabled:
        return True

    endpoint = _normalize_otlp_endpoint(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    if not endpoint:
        return False

    try:
        from opentelemetry import propagate, trace
        from opentelemetry.baggage.propagation import W3CBaggagePropagator
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    except ImportError:
        return False

    service_name = (os.getenv("OTEL_SERVICE_NAME") or default_service_name).strip() or default_service_name
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    propagate.set_global_textmap(
        CompositePropagator(
            [
                TraceContextTextMapPropagator(),
                W3CBaggagePropagator(),
            ]
        )
    )

    _trace_api = trace
    _provider = provider
    _shutdown = provider.shutdown
    _enabled = True
    _service_name = service_name
    return True


def shutdown_otel() -> None:
    """关闭当前 TracerProvider。

    该函数主要由运行时退出钩子调用，确保批量 exporter 有机会把缓存中的 span 刷出。
    """
    global _enabled, _provider, _shutdown
    if _shutdown is None:
        return
    try:
        _shutdown()
    finally:
        _enabled = False
        _provider = None
        _shutdown = None


def is_enabled() -> bool:
    """返回当前是否已经成功启用 OTEL。"""
    return _enabled


def get_tracer(name: Optional[str] = None):
    """获取 tracer；未启用 OTEL 时返回 ``None``。"""
    if not _enabled or _trace_api is None:
        return None
    return _trace_api.get_tracer(name or _service_name)


@contextmanager
def start_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Iterator[Any]:
    """创建一个 span；若 OTEL 未启用，则返回 no-op span。

    这是业务层最底层的统一入口：
    - 启用 OTEL 时：返回真实 span，并在异常路径自动记录 exception / error status；
    - 未启用 OTEL 时：返回 ``_NoopSpan``，保证调用方代码路径一致。
    """
    tracer = get_tracer()
    if tracer is None:
        yield _NoopSpan()
        return

    status = None
    status_code = None
    try:
        from opentelemetry.trace import Status, StatusCode

        status = Status
        status_code = StatusCode
    except ImportError:
        pass

    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            if status and status_code:
                span.set_status(status(status_code.ERROR, str(exc)))
            raise
