"""
LarkFlow 飞书消息发送客户端

负责：
1. 构建审批卡片消息
2. 通过 lark-oapi SDK 向飞书 IM 发送交互卡片与文本消息
3. 收口 receive_id_type / receive_id 等飞书消息协议细节
"""

import json
import os
from typing import Any

from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from pipeline.utils.lark_sdk import get_lark_client


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


def _send_message(target: str, msg_type: str, content: dict[str, Any]) -> dict[str, Any]:
    """
    通过 SDK 调用 IM v1 message.create 发送飞书消息

    @params:
        target: 消息接收方 ID，语义由 LARK_RECEIVE_ID_TYPE 决定（open_id/chat_id 等）
        msg_type: 飞书消息类型，例如 interactive 或 text
        content: 消息内容；interactive 传卡片结构，text 传 {"text": "..."}

    @return:
        返回统一结构 {"code": int, "msg": str, "data": Any}；非 0 为失败
    """
    if not target:
        return {"code": -1, "msg": "Missing Lark message target"}

    request_body = (
        CreateMessageRequestBody.builder()
        .receive_id(target)
        .msg_type(msg_type)
        .content(json.dumps(content, ensure_ascii=False))
        .build()
    )
    request = (
        CreateMessageRequest.builder()
        .receive_id_type(_get_receive_id_type())
        .request_body(request_body)
        .build()
    )

    client = get_lark_client()
    response = client.im.v1.message.create(request)

    if not response.success():
        return {"code": response.code, "msg": response.msg}

    return {
        "code": 0,
        "msg": "ok",
        "data": json.loads(response.raw.content) if response.raw and response.raw.content else None,
    }


def send_lark_card(target: str, demand_id: str, summary: str, design_doc: str) -> dict[str, Any]:
    """
    发送审批卡片到飞书

    @params:
        target: 飞书消息接收方 ID（与 LARK_RECEIVE_ID_TYPE 匹配）
        demand_id: 当前需求 ID
        summary: 设计方案摘要
        design_doc: 设计文档全文

    @return:
        返回统一响应结构 {"code": int, "msg": str, "data": Any}
    """
    return _send_message(target, "interactive", build_approval_card(demand_id, summary, design_doc))


def send_lark_text(target: str, text: str) -> dict[str, Any]:
    """
    发送普通文本消息到飞书

    @params:
        target: 飞书消息接收方 ID（与 LARK_RECEIVE_ID_TYPE 匹配）
        text: 需要发送的文本内容

    @return:
        返回统一响应结构 {"code": int, "msg": str, "data": Any}
    """
    return _send_message(target, "text", {"text": text})
