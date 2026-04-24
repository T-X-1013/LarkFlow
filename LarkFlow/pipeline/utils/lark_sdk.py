"""
LarkFlow 飞书 SDK 客户端工厂

统一收口 lark-oapi Client 的构造与复用：
1. 单例模式复用 SDK 内部的 tenant_access_token 缓存与自动刷新
2. 集中校验 LARK_APP_ID / LARK_APP_SECRET 等运行所需的环境变量
3. 其它模块通过 get_lark_client() 获取共享 client，避免重复 build
"""

import os
import threading
from typing import Optional

import lark_oapi as lark
from lark_oapi.client import Client


class LarkSdkConfigError(RuntimeError):
    """飞书 SDK 配置缺失或非法时抛出"""


_client_lock = threading.Lock()
_client: Optional[Client] = None


def _resolve_log_level() -> "lark.LogLevel":
    """
    解析 LARK_LOG_LEVEL 环境变量为 SDK 的 LogLevel 枚举

    @params:
        无入参

    @return:
        返回 lark_oapi.LogLevel 枚举；默认 INFO
    """
    raw = os.getenv("LARK_LOG_LEVEL", "INFO").strip().upper()
    mapping = {
        "DEBUG": lark.LogLevel.DEBUG,
        "INFO": lark.LogLevel.INFO,
        "WARN": lark.LogLevel.WARNING,
        "WARNING": lark.LogLevel.WARNING,
        "ERROR": lark.LogLevel.ERROR,
        "CRITICAL": lark.LogLevel.CRITICAL,
    }
    return mapping.get(raw, lark.LogLevel.INFO)


def get_lark_client() -> Client:
    """
    返回进程内共享的 lark-oapi Client 实例

    @params:
        无入参

    @return:
        返回已完成构建的 lark_oapi.client.Client；缺配置时抛 LarkSdkConfigError
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        app_id = os.getenv("LARK_APP_ID")
        app_secret = os.getenv("LARK_APP_SECRET")
        if not app_id or not app_secret:
            raise LarkSdkConfigError(
                "缺少 LARK_APP_ID 或 LARK_APP_SECRET 环境变量，无法构建飞书 SDK 客户端"
            )

        _client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(_resolve_log_level())
            .build()
        )
        return _client


def reset_lark_client() -> None:
    """
    重置单例 Client（仅供测试使用）

    @params:
        无入参

    @return:
        无返回值
    """
    global _client
    with _client_lock:
        _client = None
