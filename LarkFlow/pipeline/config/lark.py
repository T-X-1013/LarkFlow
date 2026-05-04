"""飞书/Lark 相关环境变量的集中读取层。

语义完全对齐迁移前的原地 `os.getenv` 调用：同样的 fallback、同样的 strip、
同样的默认值。所有函数 **动态读取** os.environ，不缓存，以保留测试里
`patch.dict(os.environ, ...)` 的覆盖能力。
"""

from __future__ import annotations

import os
from typing import Optional


# ---- defaults ----

# 飞书 Bot 默认按 open_id 发送消息；未显式配置时保持历史语义不变
DEFAULT_RECEIVE_ID_TYPE = "open_id"
# 日志级别统一转大写，避免大小写差异导致 SDK 行为不一致
DEFAULT_LOG_LEVEL = "INFO"
# 多维表格列名默认值必须与历史 Base 结构兼容，避免老环境未配新变量时读不到字段
DEFAULT_STATUS_FIELD = "状态"
DEFAULT_ID_FIELD = "需求 ID"
DEFAULT_DOC_FIELD = "需求文档"
DEFAULT_TECH_DOC_FIELD = "技术方案文档"
DEFAULT_TEMPLATE_FIELD = "模板"
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
    """
    读取 LARK_APP_SECRET，剥去两侧空格与引号。

    @params:
        无

    @return:
        返回清洗后的应用密钥；未配置时返回空字符串
    """
    return _strip_quoted(os.getenv("LARK_APP_SECRET"))


def chat_id() -> Optional[str]:
    """LARK_CHAT_ID 默认卡片接收目标。未配置时返回 None（与原始语义一致）。"""
    return os.getenv("LARK_CHAT_ID")


def receive_id_type() -> str:
    """
    读取 Bot 默认消息接收方 ID 类型。

    @params:
        无

    @return:
        返回 receive_id_type；未配置时回退为 open_id
    """
    return os.getenv("LARK_RECEIVE_ID_TYPE", DEFAULT_RECEIVE_ID_TYPE)


def log_level() -> str:
    """
    读取飞书 SDK 日志级别，并统一转为大写。

    @params:
        无

    @return:
        返回日志级别字符串；未配置时回退为 INFO
    """
    return os.getenv("LARK_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()


def event_store_path() -> str:
    """
    读取事件幂等 SQLite 存储路径。

    @params:
        无

    @return:
        返回配置路径；未配置时返回空字符串，由调用方决定默认位置
    """
    return (os.getenv("LARK_EVENT_STORE_PATH") or "").strip()


# ---- demand bitable ----


def demand_base_token() -> str:
    """
    读取需求 Base 的 file token。

    @params:
        无

    @return:
        返回去空白后的 Base token；未配置时返回空字符串
    """
    return (os.getenv("LARK_DEMAND_BASE_TOKEN") or "").strip()


def demand_table_id() -> str:
    """
    读取需求表 table_id。

    @params:
        无

    @return:
        返回去空白后的 table_id；未配置时返回空字符串
    """
    return (os.getenv("LARK_DEMAND_TABLE_ID") or "").strip()


def demand_status_field() -> str:
    """
    读取需求状态列名。

    @params:
        无

    @return:
        返回状态列名；未配置时回退到兼容老 Base 的默认值
    """
    return (os.getenv("LARK_DEMAND_STATUS_FIELD") or DEFAULT_STATUS_FIELD).strip()


def demand_id_field() -> str:
    """
    读取需求 ID 列名。

    @params:
        无

    @return:
        返回需求 ID 列名；未配置时回退默认值
    """
    return (os.getenv("LARK_DEMAND_ID_FIELD") or DEFAULT_ID_FIELD).strip()


def demand_doc_field() -> str:
    """
    读取需求文档列名。

    @params:
        无

    @return:
        返回需求文档列名；未配置时回退默认值
    """
    return (os.getenv("LARK_DEMAND_DOC_FIELD") or DEFAULT_DOC_FIELD).strip()


def tech_doc_field() -> str:
    """
    读取技术方案文档列名。

    @params:
        无

    @return:
        返回技术方案文档列名；未配置时回退默认值
    """
    return (os.getenv("LARK_TECH_DOC_FIELD") or DEFAULT_TECH_DOC_FIELD).strip()


def demand_template_field() -> str:
    """
    读取模板列名。

    @params:
        无

    @return:
        返回模板列名；未配置时回退默认值
    """
    return (os.getenv("LARK_DEMAND_TEMPLATE_FIELD") or DEFAULT_TEMPLATE_FIELD).strip()


def demand_requirement_field() -> str:
    return (os.getenv("LARK_DEMAND_REQUIREMENT_FIELD") or DEFAULT_REQUIREMENT_FIELD).strip()


def demand_trigger_field() -> str:
    """
    读取触发启动审批的字段列名。

    @params:
        无

    @return:
        返回触发字段列名；未配置时回退默认值
    """
    return (os.getenv("LARK_DEMAND_TRIGGER_FIELD") or DEFAULT_TRIGGER_FIELD).strip()


# ---- approval target ----


def demand_approve_target() -> str:
    """
    读取需求启动审批卡片的接收方 ID。

    @params:
        无

    @return:
        返回接收方 ID；未配置时返回空字符串
    """
    return (os.getenv("LARK_DEMAND_APPROVE_TARGET") or "").strip()


def demand_approve_receive_id_type() -> str:
    """
    读取需求启动审批卡片的接收方 ID 类型。

    @params:
        无

    @return:
        返回 receive_id_type；未配置时回退为 open_id
    """
    return (os.getenv("LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE") or DEFAULT_APPROVE_RECEIVE_ID_TYPE).strip()


# ---- docx ----


def doc_domain_override() -> Optional[str]:
    """原始语义：未配置时返回 None，由调用方拼接 _DEFAULT_DOC_DOMAIN。"""
    return os.getenv("LARK_DOC_DOMAIN")


def tech_doc_folder_token() -> str:
    """
    读取技术方案文档目录 token。

    @params:
        无

    @return:
        返回目录 token；未配置时返回空字符串
    """
    return (os.getenv("LARK_TECH_DOC_FOLDER_TOKEN") or "").strip()
