import json
import requests
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

app = FastAPI()

# ==========================================
# 1. 飞书消息卡片构建 (Lark Message Card)
# ==========================================
def build_approval_card(demand_id: str, summary: str, design_doc: str) -> dict:
    """
    构建飞书交互式消息卡片 JSON
    """
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


# ==========================================
# 2. 飞书 Webhook 回调处理 (接收用户点击)
# ==========================================
@app.post("/lark/webhook")
async def lark_webhook(request: Request):
    """
    接收飞书卡片按钮点击的回调
    """
    data = await request.json()
    
    # 1. 飞书 URL 验证挑战 (首次配置 Webhook 时需要)
    if "challenge" in data:
        return {"challenge": data["challenge"]}
    
    # 2. 兼容 V1 和 V2 格式的卡片回调解析
    action_data = data.get("action") or data.get("event", {}).get("action") or {}
    action_value = action_data.get("value", {})
    action_type = action_value.get("action")
    demand_id = action_value.get("demand_id")
    
    if not action_type or not demand_id:
        print("[Webhook] 收到无效的 action 数据:", data)
        # 飞书要求必须返回合法的卡片 JSON，否则会报 200340
        return update_card_status(f"解析失败，收到的数据: {json.dumps(data)}")

    # 3. 根据用户操作，恢复 Claude Pipeline
    if action_type == "approve":
        print(f"[Webhook] 需求 {demand_id} 已通过审批，准备进入 Coding 阶段...")
        
        # 异步执行，避免阻塞飞书回调导致超时报错
        import threading
        
        def run_resume():
            # 延迟 1 秒执行，确保 FastAPI 能先给飞书返回 200 OK
            import time
            time.sleep(1)
            resume_pipeline(demand_id, approved=True, feedback="人类已同意该设计方案。请进入 Phase 2: Coding 阶段，开始编写代码。")
            
        threading.Thread(target=run_resume).start()
        
        # 返回更新后的卡片内容（将按钮替换为“已通过”）
        return update_card_status("✅ 已通过审批，AI 正在疯狂编码中...")
        
    elif action_type == "reject":
        print(f"[Webhook] 需求 {demand_id} 被驳回，要求 AI 重新设计...")
        
        import threading
        def run_reject():
            import time
            time.sleep(1)
            resume_pipeline(demand_id, approved=False, feedback="人类驳回了该方案。请重新检查需求并修改你的设计文档。")
            
        threading.Thread(target=run_reject).start()
        
        return update_card_status("❌ 已驳回，AI 正在重新设计...")

def update_card_status(message: str) -> dict:
    """返回用于更新原飞书卡片的 JSON"""
    # 飞书要求：如果要更新卡片，直接返回卡片的 JSON 结构即可，不能包在 "card" 字段里。
    return {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🚀 状态已更新"
            },
            "template": "green"
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**{message}**"
            }
        ]
    }


# ==========================================
# 3. 恢复 Claude Pipeline (从 engine 导入)
# ==========================================
from pipeline.engine import resume_after_approval

def resume_pipeline(demand_id: str, approved: bool, feedback: str):
    """
    唤醒挂起的 Claude 上下文，并将人类的反馈作为 Tool Result 传回给 Claude
    """
    # 实际调用 engine.py 中的状态机恢复逻辑
    resume_after_approval(demand_id, approved, feedback)
