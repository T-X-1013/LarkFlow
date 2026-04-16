import json
import os
import requests
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

app = FastAPI()

# ==========================================
# 0. 应用机器人认证 (Bot API Auth)
# ==========================================
_token_cache: dict = {"token": None, "expire_at": 0}

def get_tenant_access_token() -> str:
    """
    获取应用的 tenant_access_token，带简单内存缓存（有效期内复用）
    """
    import time
    if _token_cache["token"] and time.time() < _token_cache["expire_at"]:
        return _token_cache["token"]

    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": os.getenv("LARK_APP_ID"),
            "app_secret": os.getenv("LARK_APP_SECRET"),
        },
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = time.time() + data.get("expire", 7200) - 60
    return _token_cache["token"]

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

def _receive_id_type() -> str:
    """从环境变量读取接收者类型，默认 open_id（私聊）"""
    return os.getenv("LARK_RECEIVE_ID_TYPE", "open_id")

def send_lark_card(receive_id: str, demand_id: str, summary: str, design_doc: str):
    """
    通过应用机器人 Bot API 发送交互卡片。
    receive_id 对应环境变量 LARK_CHAT_ID，类型由 LARK_RECEIVE_ID_TYPE 控制：
      open_id  → 发给指定用户（私聊，默认）
      chat_id  → 发给群聊
    """
    card_json = build_approval_card(demand_id, summary, design_doc)
    token = get_tenant_access_token()
    response = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={_receive_id_type()}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card_json),
        },
    )
    result = response.json()
    if result.get("code") != 0:
        print(f"[send_lark_card] 发送失败: {result}")
    return result

def send_lark_text(receive_id: str, text: str):
    """
    通过应用机器人 Bot API 发送文本消息。
    """
    token = get_tenant_access_token()
    response = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={_receive_id_type()}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
    )
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
    print("[Webhook] 收到请求，原始数据:", json.dumps(data, ensure_ascii=False))

    # 1. 飞书 URL 验证挑战 (首次配置 Webhook 时需要)
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    # 2. 区分事件类型
    event_type = data.get("header", {}).get("event_type", "")

    # 非卡片事件：直接忽略
    if event_type and event_type != "card.action.trigger":
        print(f"[Webhook] 收到事件: {event_type}，忽略")
        return {}

    # 卡片按钮回调：兼容 schema 2.0（action 在 event 里）和旧格式（action 在根层）
    action_data = data.get("event", {}).get("action") or data.get("action") or {}
    action_value = action_data.get("value", {})
    action_type = action_value.get("action")
    demand_id = action_value.get("demand_id")

    if not action_type or not demand_id:
        print("[Webhook] 收到无法解析的卡片回调数据:", data)
        return {}

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
    # 飞书卡片 1.0 回调响应规范：
    # - 直接将卡片内容放在根层，不能用 "card" 字段包裹（无 toast 时）
    # - 不能带 "schema" 字段，否则飞书按 2.0 解析，elements 字段不合法 → 200340
    # 如需同时更新卡片 + 弹 toast，格式为：{"toast": {...}, "card": {card_content}}
    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "状态已更新"
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
# 3. Pipeline 控制 (从 engine 导入，同进程共享 SESSION_STORE)
# ==========================================
from pipeline.engine import resume_after_approval, start_new_demand

def resume_pipeline(demand_id: str, approved: bool, feedback: str):
    """唤醒挂起的 Claude 上下文"""
    resume_after_approval(demand_id, approved, feedback)


# ==========================================
# 4. 启动新需求的接口
# ==========================================
@app.post("/start")
async def start_demand(request: Request):
    """
    触发新需求 Pipeline。
    Body: {"demand_id": "DEMAND-001", "requirement": "需求描述"}
    """
    data = await request.json()
    demand_id = data.get("demand_id")
    requirement = data.get("requirement")
    if not demand_id or not requirement:
        raise HTTPException(status_code=400, detail="demand_id 和 requirement 不能为空")

    import threading
    threading.Thread(
        target=start_new_demand,
        args=(demand_id, requirement),
        daemon=True
    ).start()

    return {"status": "started", "demand_id": demand_id}
