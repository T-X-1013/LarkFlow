"""
LarkFlow 飞书消息发送客户端

负责：
1. 构建审批卡片消息
2. 统一通过群机器人 Webhook 或 Bot API 发送飞书消息
3. 收口飞书消息发送所需的目标地址、token 与请求格式
"""

import json
import os
from typing import Any, Optional

import requests

from pipeline.utils.lark_doc import get_tenant_access_token


def build_approval_card(demand_id: str, summary: str, design_doc: str) -> dict[str, Any]:
    """
    构建飞书交互式审批卡片

    @params:
        demand_id: 当前需求 ID
        summary: 设计方案摘要
        design_doc: 设计文档全文

    @return:
        返回可直接发送给飞书的卡片 JSON 结构
    """
    display_doc = design_doc[:500] + "..." if len(design_doc) > 500 else design_doc

    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🚀 AI 架构设计审批 (需求 ID: {demand_id})",
            },
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    "**AI 助手已完成技术方案设计，请审批：**\n\n"
                    f"**📝 方案摘要**\n{summary}\n\n"
                    f"**📄 详细设计 (部分)**\n{display_doc}"
                ),
            },
            {
                "tag": "hr",
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ 同意并进入编码阶段",
                        },
                        "type": "primary",
                        "value": {
                            "action": "approve",
                            "demand_id": demand_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ 驳回并要求修改",
                        },
                        "type": "danger",
                        "value": {
                            "action": "reject",
                            "demand_id": demand_id,
                        },
                    },
                ],
            },
        ],
    }


def _get_receive_id_type() -> str:
    """
    读取 Bot API 的接收方 ID 类型

    @params:
        无入参

    @return:
        返回发送消息时使用的 receive_id_type；默认值为 open_id
    """
    return os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")


def _build_message_api_url() -> str:
    """
    构造飞书 Bot API 的消息发送地址

    @params:
        无入参

    @return:
        返回带 receive_id_type 查询参数的消息发送 URL
    """
    receive_id_type = _get_receive_id_type()
    return f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    发送 JSON 请求并返回 JSON 响应

    @params:
        url: 请求目标地址
        payload: 需要发送的 JSON 载荷
        headers: 可选请求头

    @return:
        返回飞书接口的 JSON 响应；请求失败时返回统一错误结构
    """
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"code": -1, "msg": str(exc)}


def _send_message(target: str, msg_type: str, content: dict[str, Any]) -> dict[str, Any]:
    """
    按目标类型统一发送飞书消息

    @params:
        target: 目标地址；可以是群机器人 webhook，也可以是 chat_id/open_id
        msg_type: 飞书消息类型，例如 interactive 或 text
        content: 消息内容；interactive 传卡片结构，text 传 {"text": "..."}

    @return:
        返回飞书接口的 JSON 响应
    """
    if not target:
        return {"code": -1, "msg": "Missing Lark message target"}

    if target.startswith("http"):
        payload = {
            "msg_type": msg_type,
            "card": content if msg_type == "interactive" else None,
            "content": content if msg_type != "interactive" else None,
        }
        # 群机器人接口不接受值为 None 的多余字段，这里显式裁剪无效字段
        payload = {key: value for key, value in payload.items() if value is not None}
        return _post_json(target, payload)

    access_token = get_tenant_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "receive_id": target,
        "msg_type": msg_type,
        # Bot API 要求 content 是 JSON 字符串，而不是嵌套对象
        "content": json.dumps(content, ensure_ascii=False),
    }
    return _post_json(_build_message_api_url(), payload, headers=headers)


def send_lark_card(target: str, demand_id: str, summary: str, design_doc: str) -> dict[str, Any]:
    """
    发送审批卡片到飞书

    @params:
        target: 飞书消息目标；可以是 webhook 或 receive_id
        demand_id: 当前需求 ID
        summary: 设计方案摘要
        design_doc: 设计文档全文

    @return:
        返回飞书接口的 JSON 响应
    """
    return _send_message(target, "interactive", build_approval_card(demand_id, summary, design_doc))


def send_lark_text(target: str, text: str) -> dict[str, Any]:
    """
    发送普通文本消息到飞书

    @params:
        target: 飞书消息目标；可以是 webhook 或 receive_id
        text: 需要发送的文本内容

    @return:
        返回飞书接口的 JSON 响应
    """
    return _send_message(target, "text", {"text": text})
