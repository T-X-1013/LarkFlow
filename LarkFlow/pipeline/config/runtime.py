"""LarkFlow 运行时配置集中读取层。

覆盖 LARKFLOW_* / UVICORN_* / PIPELINE_HTTP_* / DATABASE_URL 以及部署相关的
镜像/代理镜像源等 env。和 `llm.py` / `lark.py` 一样，全部 **动态读取**，
默认值与原地 `os.getenv` 调用等价。
"""

from __future__ import annotations

import os
from typing import Optional


# ---- session persistence ----

DEFAULT_SESSION_DB = ".larkflow/sessions.db"


def session_db_path() -> str:
    return os.getenv("LARKFLOW_SESSION_DB", DEFAULT_SESSION_DB)


# ---- logging ----

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FILE = "logs/larkflow.jsonl"


def log_level() -> str:
    """原地 `os.getenv("LARKFLOW_LOG_LEVEL", "INFO").upper()` 对应。"""
    return os.getenv("LARKFLOW_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()


def log_file() -> str:
    return os.getenv("LARKFLOW_LOG_FILE", DEFAULT_LOG_FILE)


# ---- uvicorn / http ----

DEFAULT_UVICORN_LOG_LEVEL = "info"
DEFAULT_HTTP_HOST = "0.0.0.0"
DEFAULT_HTTP_PORT = 8000


def uvicorn_log_level() -> str:
    return os.getenv("UVICORN_LOG_LEVEL", DEFAULT_UVICORN_LOG_LEVEL)


def http_host() -> str:
    return os.getenv("PIPELINE_HTTP_HOST", DEFAULT_HTTP_HOST)


def http_port() -> int:
    return int(os.getenv("PIPELINE_HTTP_PORT", str(DEFAULT_HTTP_PORT)))


# ---- database (tools_runtime) ----


def database_url() -> Optional[str]:
    """返回 `.strip()` 后的 DATABASE_URL；未配置返回空串，由调用方处理。"""
    return (os.getenv("DATABASE_URL") or "").strip()


# ---- deploy / build args ----


def deploy_go_image() -> str:
    return os.getenv("LARKFLOW_GO_IMAGE", "")


def deploy_alpine_mirror() -> str:
    return os.getenv("LARKFLOW_ALPINE_MIRROR", "")


def deploy_go_proxy() -> str:
    return os.getenv("LARKFLOW_GO_PROXY", "")


# ---- generic helper (engine._get_env_int) ----


def env_positive_int(name: str, default: int) -> int:
    """读取正整数 env；缺失或非法时回退 default（最低 1）。

    对应 engine.py 里原 `_get_env_int` 的语义，搬到这里供其它模块复用。
    """
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default
