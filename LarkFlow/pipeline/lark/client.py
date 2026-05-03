"""
LarkFlow 飞书消息发送客户端

负责：
1. 构建审批卡片消息
2. 通过 lark-oapi SDK 向飞书 IM 发送交互卡片与文本消息
3. 收口 receive_id_type / receive_id 等飞书消息协议细节
"""

import json
import os
from typing import Any, Optional

from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from pipeline.lark.sdk import get_lark_client


def build_approval_card(
    demand_id: str,
    summary: str,
    design_doc: str = "",
    tech_doc_url: Optional[str] = None,
    tech_doc_title: Optional[str] = None,
) -> dict[str, Any]:
    """
    构建飞书交互式审批卡片

    @params:
        demand_id: 当前需求 ID
        summary: 设计方案摘要
        design_doc: 设计文档全文；无 tech_doc_url 时按旧逻辑截断 500 字展示
        tech_doc_url: 飞书文档链接；非空时卡片用"📄 查看完整技术方案"链接替代截断正文
        tech_doc_title: 链接文案，默认"查看完整技术方案"

    @return:
        返回可直接发送给飞书的卡片 JSON 结构
    """
    if tech_doc_url:
        link_text = tech_doc_title or "查看完整技术方案"
        detail_section = (
            f"**📄 详细设计**\n[{link_text}]({tech_doc_url})"
        )
    else:
        display_doc = design_doc[:500] + "..." if len(design_doc) > 500 else design_doc
        detail_section = f"**📄 详细设计 (部分)**\n{display_doc}"

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
                    f"{detail_section}"
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


def _send_message(
    target: str,
    msg_type: str,
    content: dict[str, Any],
    receive_id_type: Optional[str] = None,
) -> dict[str, Any]:
    """
    通过 SDK 调用 IM v1 message.create 发送飞书消息

    @params:
        target: 消息接收方 ID，语义由 receive_id_type 决定（open_id/chat_id 等）
        msg_type: 飞书消息类型，例如 interactive 或 text
        content: 消息内容；interactive 传卡片结构，text 传 {"text": "..."}
        receive_id_type: 显式指定的 receive_id_type；为空时回退到 LARK_RECEIVE_ID_TYPE

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
        .receive_id_type(receive_id_type or _get_receive_id_type())
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


def send_lark_card(
    target: str,
    demand_id: str,
    summary: str,
    design_doc: str = "",
    tech_doc_url: Optional[str] = None,
    tech_doc_title: Optional[str] = None,
) -> dict[str, Any]:
    """
    发送审批卡片到飞书；tech_doc_url 非空时卡片走"飞书文档链接"渲染，否则回退到截断正文

    @params:
        target: 飞书消息接收方 ID（与 LARK_RECEIVE_ID_TYPE 匹配）
        demand_id: 当前需求 ID
        summary: 设计方案摘要
        design_doc: 设计文档全文；当 tech_doc_url 为空时用作截断展示
        tech_doc_url: 飞书文档链接；优先渲染为可点击链接
        tech_doc_title: 链接文案，默认"查看完整技术方案"

    @return:
        返回统一响应结构 {"code": int, "msg": str, "data": Any}
    """
    card = build_approval_card(
        demand_id,
        summary,
        design_doc=design_doc,
        tech_doc_url=tech_doc_url,
        tech_doc_title=tech_doc_title,
    )
    return _send_message(target, "interactive", card)


def send_lark_card_raw(target: str, card: dict[str, Any]) -> dict[str, Any]:
    """直接发送已构建好的卡片 JSON（绕过 build_approval_card 固定模板）。

    D3 第 2 HITL deploy 卡片不走 design 卡片模板，直接传 lark_cards 构建的 JSON。
    """
    return _send_message(target, "interactive", card)


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


def build_demand_start_card(
    demand_id: str,
    doc_url: str,
    base_token: str,
    table_id: str,
    record_id: str,
) -> dict[str, Any]:
    """
    构建「新需求启动审批」交互式卡片（对应方案 B 的入口卡片）

    @params:
        demand_id: Base 里的业务唯一键（需求ID 列值）
        doc_url: 需求文档链接
        base_token: 需求 Base 的 file_token，用于按钮回调时写回状态列
        table_id: 需求表的 table_id
        record_id: 当前记录 record_id

    @return:
        返回可直接发送给飞书的卡片 JSON 结构
    """
    base_ctx = {
        "base_token": base_token,
        "table_id": table_id,
        "record_id": record_id,
        "demand_id": demand_id,
    }

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🆕 新需求待启动 (需求 ID: {demand_id})",
            },
            "template": "orange",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    "**Base 里新增了一条需求，请确认是否启动 AI 流水线：**\n\n"
                    f"**📌 需求 ID**：{demand_id}\n\n"
                    f"**📄 需求文档**：{doc_url or '（未提供）'}\n"
                ),
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🚀 开始处理"},
                        "type": "primary",
                        "value": {
                            "action": "start_demand",
                            "doc_url": doc_url,
                            **base_ctx,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 驳回"},
                        "type": "danger",
                        "value": {
                            "action": "reject_demand",
                            **base_ctx,
                        },
                    },
                ],
            },
        ],
    }


def send_demand_start_card(
    target: str,
    demand_id: str,
    doc_url: str,
    base_token: str,
    table_id: str,
    record_id: str,
    receive_id_type: str = "open_id",
) -> dict[str, Any]:
    """
    把「新需求启动审批」卡片发送到指定接收方

    target + receive_id_type 由 env（LARK_DEMAND_APPROVE_TARGET / LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE）
    决定，可发到群聊或个人私聊。

    @params:
        target: 接收方 ID
        demand_id: 需求 ID
        doc_url: 需求文档链接
        base_token: Base 的 file_token
        table_id: 需求表 table_id
        record_id: 需求行 record_id
        receive_id_type: 接收方 ID 类型，默认 open_id

    @return:
        返回统一响应结构 {"code": int, "msg": str, "data": Any}
    """
    card = build_demand_start_card(demand_id, doc_url, base_token, table_id, record_id)
    return _send_message(target, "interactive", card, receive_id_type=receive_id_type)
