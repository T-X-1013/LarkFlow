import json
import requests
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

app = FastAPI()

# ==========================================
# 0. 飞书消息发送工具 (移至顶部，避免循环导入)
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
    
    # 如果 webhook_url 是以 http 开头的，说明是群机器人的 webhook
    if webhook_url.startswith("http"):
        payload = {
            "msg_type": "interactive",
            "card": card_json
        }
        response = requests.post(webhook_url, json=payload)
        return response.json()
    
    # 如果 webhook_url 不是 http 开头的（比如是一个 open_id），说明你想通过 API 发送给个人或群
    # 这需要调用飞书的发送消息 API
    else:
        from pipeline.utils.lark_doc import get_tenant_access_token
        
        try:
            access_token = get_tenant_access_token()
            api_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
            
            # 检查是否配置了 LARK_RECEIVE_ID_TYPE
            import os
            receive_id_type = os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")
            api_url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "receive_id": webhook_url, # 这里 webhook_url 实际上是 chat_id 或 open_id
                "msg_type": "interactive",
                "content": json.dumps(card_json)
            }
            
            response = requests.post(api_url, headers=headers, json=payload)
            return response.json()
        except Exception as e:
            print(f"[Error] 发送飞书卡片失败: {e}")
            return {"code": -1, "msg": str(e)}

def send_lark_text(webhook_url: str, text: str):
    """
    发送普通文本消息到飞书
    """
    if webhook_url.startswith("http"):
        payload = {
            "msg_type": "text",
            "content": {"text": text}
        }
        response = requests.post(webhook_url, json=payload)
        return response.json()
    else:
        from pipeline.utils.lark_doc import get_tenant_access_token
        
        try:
            access_token = get_tenant_access_token()
            import os
            receive_id_type = os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")
            api_url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "receive_id": webhook_url,
                "msg_type": "text",
                "content": json.dumps({"text": text})
            }
            
            response = requests.post(api_url, headers=headers, json=payload)
            return response.json()
        except Exception as e:
            print(f"[Error] 发送飞书文本失败: {e}")
            return {"code": -1, "msg": str(e)}

# ==========================================
# 1. 飞书 Webhook 回调处理 (接收用户点击)
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
        
    # 2. 检查是否是多维表格的“开始执行”按钮触发
    if data.get("action") == "start_demand":
        # 飞书多维表格传过来的参数可能在 data.get("demand_id") 或者嵌套在别的地方
        # 我们需要更灵活地解析它
        demand_id = str(data.get("demand_id", ""))
        doc_url = data.get("doc_url", "")
        
        # 打印出飞书传过来的最原始的 doc_url 数据结构，方便排查
        print(f"[Debug] 原始 doc_url 数据: type={type(doc_url)}, value={doc_url}")
        
        # 飞书多维表格如果配置了“文档链接”类型的字段，它传过来的可能是一个包含 link 和 text 的列表/字典
        # 例如: [{"text": "需求", "link": "https://..."}]
        if isinstance(doc_url, list) and len(doc_url) > 0 and isinstance(doc_url[0], dict):
            doc_url = doc_url[0].get("link", doc_url[0].get("text", ""))
        elif isinstance(doc_url, dict):
            doc_url = doc_url.get("link", doc_url.get("text", ""))
            
        doc_url = str(doc_url)
        
        # 兼容飞书多维表格未替换成功的变量格式 (如 "{{1}}", "{{需求}}")
        import re
        import time
        if not demand_id or re.match(r'^\{\{.*\}\}$', demand_id):
            demand_id = "DEMAND-" + str(int(time.time()))
            
        if not doc_url or re.match(r'^\{\{.*\}\}$', doc_url):
            doc_url = "未提供具体文档链接，请根据后续对话补充需求。"
            
        # 兼容飞书多维表格传过来的纯文本 "需求" (如果你在表格里填的是文字而不是链接)
        if doc_url == "需求" or doc_url == "[{'text': '需求'}]":
            doc_url = "未提供具体文档链接，请根据后续对话补充需求。"
            
        # 如果 doc_url 不是完整的 http 链接，但你希望它能被当做文档处理
        # 飞书多维表格在发送“关联文档”字段时，如果配置不当，可能只会发送文档标题（比如"需求"）
        # 解决方案：在飞书多维表格的“发送HTTP请求”配置中，不要选择“需求文档”，而是选择“需求文档.链接”或“需求文档.URL”
        
        print(f"[Webhook] 收到多维表格触发，开始处理新需求: {demand_id}, 文档: {doc_url}")
        
        import threading
        import time
        def run_start():
            from pipeline.engine import start_new_demand
            
            # 如果 doc_url 是一个飞书链接，尝试读取其内容
            if "feishu.cn" in doc_url or "larksuite.com" in doc_url:
                from pipeline.utils.lark_doc import fetch_lark_doc_content
                print(f"[Webhook] 检测到飞书文档链接，尝试读取内容: {doc_url}")
                doc_content = fetch_lark_doc_content(doc_url)
                requirement = f"请查阅此需求文档并进行技术方案设计：\n\n【文档链接】\n{doc_url}\n\n【文档内容】\n{doc_content}"
            else:
                requirement = f"请查阅此需求文档并进行技术方案设计：{doc_url}"
                
            start_new_demand(demand_id, requirement)
            
        threading.Thread(target=run_start).start()
        return {"code": 0, "msg": "success"}
    
    # 3. 兼容 V1 和 V2 格式的卡片回调解析
    action_data = data.get("action") or data.get("event", {}).get("action") or {}
    
    # 忽略飞书推送的其他事件（比如机器人进群、有人@机器人等）
    # 这些事件的 header.event_type 通常是 im.chat.xxx
    if data.get("header", {}).get("event_type"):
        event_type = data.get("header").get("event_type")
        print(f"[Webhook] 忽略非卡片点击事件: {event_type}")
        return {"code": 0, "msg": "ignored"}
        
    # 如果 action_data 是字符串（比如其他未知的按钮触发），直接忽略
    if isinstance(action_data, str):
        return {"error": "Unknown action format"}
        
    action_value = action_data.get("value", {})
    action_type = action_value.get("action")
    demand_id = action_value.get("demand_id")
    
    if not action_type or not demand_id:
        print("[Webhook] 收到无效的 action 数据:", data)
        # 飞书要求必须返回合法的卡片 JSON，否则会报 200340
        return update_card_status(f"解析失败，收到的数据: {json.dumps(data)}")

    # 4. 根据用户操作，恢复 Agent Pipeline
    if action_type == "approve":
        print(f"[Webhook] 需求 {demand_id} 已通过审批，准备进入 Coding 阶段...")
        
        # 异步执行，避免阻塞飞书回调导致超时报错
        import threading
        
        def run_resume():
            # 延迟 1 秒执行，确保 FastAPI 能先给飞书返回 200 OK
            import time
            time.sleep(1)
            from pipeline.engine import resume_after_approval
            resume_after_approval(demand_id, approved=True, feedback="人类已同意该设计方案。请进入 Phase 2: Coding 阶段，开始编写代码。")
            
        threading.Thread(target=run_resume).start()
        
        # 返回更新后的卡片内容（将按钮替换为“已通过”）
        return update_card_status("✅ 已通过审批，AI 正在疯狂编码中...")
        
    elif action_type == "reject":
        print(f"[Webhook] 需求 {demand_id} 被驳回，要求 AI 重新设计...")
        
        import threading
        def run_reject():
            import time
            time.sleep(1)
            from pipeline.engine import resume_after_approval
            resume_after_approval(demand_id, approved=False, feedback="人类驳回了该方案。请重新检查需求并修改你的设计文档。")
            
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
