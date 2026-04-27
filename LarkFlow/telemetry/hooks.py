"""Thin OTEL hook layer to reduce merge conflicts in business modules.

Keep tracing naming/attribute details in one place so callers only import a
small set of context managers and setup helpers.
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from telemetry.otel import init_otel, shutdown_otel, start_span

_shutdown_registered = False


def setup_runtime_otel(default_service_name: str = "larkflow") -> None:
    """Initialize OTEL once and register shutdown handler when enabled."""
    global _shutdown_registered

    if not init_otel(default_service_name):
        return
    if _shutdown_registered:
        return
    atexit.register(shutdown_otel)
    _shutdown_registered = True


@contextmanager
def trace_lark_start_request(demand_id: str, doc_url: str) -> Iterator[Any]:
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
) -> Iterator[Any]:
    with start_span(
        f"phase.{phase}",
        {
            "demand_id": demand_id,
            "phase": phase,
            "prompt_file": prompt_file,
        },
    ) as span:
        yield span


@contextmanager
def trace_demand_start(demand_id: str, phase: str) -> Iterator[Any]:
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
    with start_span(
        "phase.deploying",
        {
            "demand_id": demand_id,
            "phase": phase,
        },
    ) as span:
        yield span
