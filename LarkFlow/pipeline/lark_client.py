import requests


# ==========================================
# 1. 飞书消息卡片构建 (Lark Message Card)
# ==========================================
def build_approval_card(demand_id: str, summary: str, design_doc: str) -> dict:
    """
    构建飞书交互式消息卡片 JSON
    """
    # todo 目前文档的展示超过500就被截断了，用户观感不好，后续需要优化
    # todo 目前“同意并进入编码阶段”被多次点击后会产生多个请求，这会导致报错
    # 截断过长的设计文档，避免卡片超长
    display_doc = design_doc[:500] + "..." if len(design_doc) > 500 else design_doc

    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🚀 AI 架构设计审批 (需求 ID: {demand_id})"
            },
            "template": "blue"
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**AI 助手已完成技术方案设计，请审批：**\n\n**📝 方案摘要**\n{summary}\n\n**📄 详细设计 (部分)**\n{display_doc}"
            },
            {
                "tag": "hr"
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ 同意并进入编码阶段"
                        },
                        "type": "primary",
                        "value": {
                            "action": "approve",
                            "demand_id": demand_id
                        }
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "❌ 驳回并要求修改"
                        },
                        "type": "danger",
                        "value": {
                            "action": "reject",
                            "demand_id": demand_id
                        }
                    }
                ]
            }
        ]
    }


def send_lark_card(webhook_url: str, demand_id: str, summary: str, design_doc: str):
    """
    发送卡片到飞书群聊或个人
    """
    card_json = build_approval_card(demand_id, summary, design_doc)
    payload = {
        "msg_type": "interactive",
        "card": card_json
    }
    response = requests.post(webhook_url, json=payload)
    return response.json()


def send_lark_text(webhook_url: str, text: str):
    """
    发送普通文本消息到飞书
    """
    payload = {
        "msg_type": "text",
        "content": {"text": text}
    }
    response = requests.post(webhook_url, json=payload)
    return response.json()