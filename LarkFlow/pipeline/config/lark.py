"""飞书/Lark 相关环境变量的集中读取层。

语义完全对齐迁移前的原地 `os.getenv` 调用：同样的 fallback、同样的 strip、
同样的默认值。所有函数 **动态读取** os.environ，不缓存，以保留测试里
`patch.dict(os.environ, ...)` 的覆盖能力。
"""

from __future__ import annotations

import os
from typing import Optional


# ---- defaults ----

DEFAULT_RECEIVE_ID_TYPE = "open_id"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_STATUS_FIELD = "状态"
DEFAULT_ID_FIELD = "需求ID"
DEFAULT_DOC_FIELD = "需求文档"
DEFAULT_TECH_DOC_FIELD = "技术方案文档"
DEFAULT_TRIGGER_FIELD = "触发时间"
DEFAULT_APPROVE_RECEIVE_ID_TYPE = "open_id"
DEFAULT_REQUIREMENT_FIELD = "需求描述"


def _strip_quoted(value: Optional[str]) -> str:
    """对齐 sdk.py / interaction.py 的 `.strip().strip('\"').strip(\"'\")` 处理。"""
    return (value or "").strip().strip('"').strip("'")


# ---- bot credentials ----


def app_id() -> str:
    """读取 LARK_APP_ID，剥去两侧空格与引号。"""
    return _strip_quoted(os.getenv("LARK_APP_ID"))


def app_secret() -> str:
    return _strip_quoted(os.getenv("LARK_APP_SECRET"))


def chat_id() -> Optional[str]:
    """LARK_CHAT_ID 默认卡片接收目标。未配置时返回 None（与原始语义一致）。"""
    return os.getenv("LARK_CHAT_ID")


def receive_id_type() -> str:
    return os.getenv("LARK_RECEIVE_ID_TYPE", DEFAULT_RECEIVE_ID_TYPE)


def log_level() -> str:
    return os.getenv("LARK_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()


def event_store_path() -> str:
    return (os.getenv("LARK_EVENT_STORE_PATH") or "").strip()


# ---- demand bitable ----


def demand_base_token() -> str:
    return (os.getenv("LARK_DEMAND_BASE_TOKEN") or "").strip()


def demand_table_id() -> str:
    return (os.getenv("LARK_DEMAND_TABLE_ID") or "").strip()


def demand_status_field() -> str:
    return (os.getenv("LARK_DEMAND_STATUS_FIELD") or DEFAULT_STATUS_FIELD).strip()


def demand_id_field() -> str:
    return (os.getenv("LARK_DEMAND_ID_FIELD") or DEFAULT_ID_FIELD).strip()


def demand_doc_field() -> str:
    return (os.getenv("LARK_DEMAND_DOC_FIELD") or DEFAULT_DOC_FIELD).strip()


def tech_doc_field() -> str:
    return (os.getenv("LARK_TECH_DOC_FIELD") or DEFAULT_TECH_DOC_FIELD).strip()


def demand_requirement_field() -> str:
    return (os.getenv("LARK_DEMAND_REQUIREMENT_FIELD") or DEFAULT_REQUIREMENT_FIELD).strip()


def demand_trigger_field() -> str:
    return (os.getenv("LARK_DEMAND_TRIGGER_FIELD") or DEFAULT_TRIGGER_FIELD).strip()


# ---- approval target ----


def demand_approve_target() -> str:
    return (os.getenv("LARK_DEMAND_APPROVE_TARGET") or "").strip()


def demand_approve_receive_id_type() -> str:
    return (os.getenv("LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE") or DEFAULT_APPROVE_RECEIVE_ID_TYPE).strip()


# ---- docx ----


def doc_domain_override() -> Optional[str]:
    """原始语义：未配置时返回 None，由调用方拼接 _DEFAULT_DOC_DOMAIN。"""
    return os.getenv("LARK_DOC_DOMAIN")


def tech_doc_folder_token() -> str:
    return (os.getenv("LARK_TECH_DOC_FOLDER_TOKEN") or "").strip()
