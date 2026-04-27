"""OpenTelemetry helpers for LarkFlow.

The integration is intentionally minimal:
1. No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
2. Lazy import OpenTelemetry dependencies so local workflows can still run
   before dependencies are installed.
3. Expose a small context-manager API for manual spans.
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
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None


def _normalize_otlp_endpoint(raw: str) -> str:
    endpoint = (raw or "").strip()
    if endpoint.startswith("http://"):
        return endpoint[len("http://") :]
    if endpoint.startswith("https://"):
        return endpoint[len("https://") :]
    return endpoint


def init_otel(default_service_name: str = "larkflow") -> bool:
    """Initialize OTEL exporter when endpoint is configured.

    Returns True when OTEL is enabled, otherwise False.
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
    return _enabled


def get_tracer(name: Optional[str] = None):
    if not _enabled or _trace_api is None:
        return None
    return _trace_api.get_tracer(name or _service_name)


@contextmanager
def start_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Iterator[Any]:
    """Start a span or yield a no-op span when OTEL is disabled."""
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
