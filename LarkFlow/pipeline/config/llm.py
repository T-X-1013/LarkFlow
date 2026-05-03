"""LLM 相关配置的集中读取层。

所有函数都 **动态读取** 环境变量（不缓存），以保持和原先 `os.getenv` 调用的
等价语义——现有单测通过 `patch.dict(os.environ, ...)` 在运行时切换配置，
若此处加缓存会导致测试行为回退。

env 名称、默认值和 fallback 优先级必须与 `pipeline/llm/adapter.py` 迁移前
一致，PR1 只做"搬家"，不做语义变更。
"""

from __future__ import annotations

import os
from typing import List, Optional


# ---- provider ----

DEFAULT_PROVIDER = "anthropic"


def provider_from_env() -> str:
    """读取 `LLM_PROVIDER`；未配置时回退到默认 anthropic。"""
    return os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER)


# ---- anthropic ----

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"


def anthropic_api_key() -> Optional[str]:
    """优先读 ANTHROPIC_AUTH_TOKEN，回退 ANTHROPIC_API_KEY。"""
    return os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")


def anthropic_base_url() -> Optional[str]:
    return os.getenv("ANTHROPIC_BASE_URL") or None


def anthropic_model() -> str:
    return os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)


# ---- openai ----

DEFAULT_OPENAI_MODEL = "gpt-5-codex"


def openai_api_key() -> Optional[str]:
    return os.getenv("OPENAI_API_KEY")


def openai_base_url() -> Optional[str]:
    return os.getenv("OPENAI_BASE_URL") or None


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def openai_model_env_names() -> List[str]:
    """Responses API 路径里按优先级读取模型名的 env 列表。"""
    return ["OPENAI_MODEL"]


def openai_reasoning_env_name() -> str:
    return "OPENAI_REASONING_EFFORT"


def openai_retry_env_prefix() -> str:
    return "OPENAI"


# ---- qwen / dashscope ----

DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-plus"  # 与 _create_qwen_turn 内 fallback 对齐
DEFAULT_QWEN_MODEL_RESOLVER = "qwen3.6-plus"  # _resolve_qwen_model_name 原 fallback


def qwen_api_key() -> Optional[str]:
    return os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")


def qwen_base_url() -> str:
    return (
        os.getenv("QWEN_BASE_URL")
        or os.getenv("DASHSCOPE_BASE_URL")
        or DEFAULT_QWEN_BASE_URL
    )


def qwen_resolver_model() -> str:
    """`_resolve_qwen_model_name` 场景：登记 provider 时的模型展示名。"""
    return (
        os.getenv("QWEN_MODEL")
        or os.getenv("DASHSCOPE_MODEL")
        or DEFAULT_QWEN_MODEL_RESOLVER
    )


def qwen_turn_model() -> str:
    """`_create_qwen_turn` 场景：实际发请求时用的模型名。"""
    return (
        os.getenv("QWEN_MODEL")
        or os.getenv("DASHSCOPE_MODEL")
        or DEFAULT_QWEN_MODEL
    )


# ---- doubao / ark ----

DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def doubao_api_key() -> Optional[str]:
    return os.getenv("DOUBAO_API_KEY") or os.getenv("ARK_API_KEY")


def doubao_base_url() -> str:
    return (
        os.getenv("DOUBAO_BASE_URL")
        or os.getenv("ARK_BASE_URL")
        or DEFAULT_DOUBAO_BASE_URL
    )


def doubao_model() -> str:
    return (
        os.getenv("DOUBAO_MODEL")
        or os.getenv("ARK_MODEL")
        or os.getenv("ARK_ENDPOINT_ID")
        or ""
    )


def doubao_model_env_names() -> List[str]:
    return ["DOUBAO_MODEL", "ARK_MODEL", "ARK_ENDPOINT_ID"]


def doubao_retry_env_prefix() -> str:
    return "DOUBAO"


# ---- retry / misc ----


def retry_max_retries(env_prefix: str, default: int = 3) -> int:
    return int(os.getenv(f"{env_prefix}_MAX_RETRIES", str(default)))


def retry_base_seconds(env_prefix: str, default: float = 5.0) -> float:
    return float(os.getenv(f"{env_prefix}_RETRY_BASE_SECONDS", str(default)))


def retry_max_seconds(env_prefix: str, default: float = 60.0) -> float:
    return float(os.getenv(f"{env_prefix}_RETRY_MAX_SECONDS", str(default)))


def reasoning_effort(env_name: str, default: str = "medium") -> str:
    return os.getenv(env_name, default).strip()


def first_env_value(names: List[str], default: str = "") -> str:
    """按优先级读取第一项非空 env。"""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default
