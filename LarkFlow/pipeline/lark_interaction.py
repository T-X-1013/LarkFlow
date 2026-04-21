"""
LarkFlow 飞书 Webhook 入口

负责：
1. 校验飞书回调的 verification token、签名与可选加密载荷
2. 对 event_id 做 24 小时幂等，避免重复点击或重复推送多次触发 pipeline
3. 接收飞书回调与启动请求，并唤醒对应的需求流程
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from lark_oapi.core.const import (
    LARK_REQUEST_NONCE,
    LARK_REQUEST_SIGNATURE,
    LARK_REQUEST_TIMESTAMP,
    URL_VERIFICATION,
)
from lark_oapi.core.utils.decryptor import AESCipher

from pipeline.utils.lark_doc import fetch_lark_doc_content


app = FastAPI()

# 飞书回调事件默认保留 24 小时，确保同一事件重复投递时不会再次触发 pipeline
EVENT_ID_TTL_SECONDS = 24 * 60 * 60


def _project_root() -> Path:
    """
    返回 LarkFlow Python 项目根目录

    @params:
        无入参

    @return:
        返回当前文件所在的 LarkFlow 项目根目录路径
    """
    return Path(__file__).resolve().parents[1]


def _event_store_path() -> Path:
    """
    解析飞书事件幂等存储路径

    @params:
        无入参

    @return:
        返回用于保存 event_id 的 SQLite 文件路径
    """
    configured_path = (os.getenv("LARK_EVENT_STORE_PATH") or "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return _project_root() / "tmp" / "lark_event_store.db"


def _ensure_event_store() -> Path:
    """
    确保飞书事件幂等 SQLite 表存在

    @params:
        无入参

    @return:
        返回可直接使用的 SQLite 数据库文件路径
    """
    store_path = _event_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(store_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lark_event_dedup (
                event_id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        connection.commit()

    return store_path


def _remember_event_id(event_id: str) -> bool:
    """
    记录 event_id，并判断是否首次出现

    @params:
        event_id: 飞书回调 header 中的事件 ID

    @return:
        首次写入返回 True；已处理过的重复事件返回 False
    """
    if not event_id:
        return True

    store_path = _ensure_event_store()
    now = int(time.time())
    expires_at = now + EVENT_ID_TTL_SECONDS

    with sqlite3.connect(str(store_path)) as connection:
        # 每次写入前顺手清理过期事件，保持 24h TTL 语义稳定
        connection.execute(
            "DELETE FROM lark_event_dedup WHERE expires_at <= ?",
            (now,),
        )
        try:
            connection.execute(
                """
                INSERT INTO lark_event_dedup (event_id, created_at, expires_at)
                VALUES (?, ?, ?)
                """,
                (event_id, now, expires_at),
            )
            connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def _decrypt_lark_payload(raw_body: bytes, encrypt_key: str) -> str:
    """
    解密飞书 encrypt 载荷

    @params:
        raw_body: 飞书回调原始请求体
        encrypt_key: 飞书事件订阅配置中的加密密钥

    @return:
        返回解密后的 JSON 文本
    """
    body = json.loads(raw_body.decode("utf-8"))
    encrypted_text = body.get("encrypt")
    if not encrypted_text:
        return raw_body.decode("utf-8")
    if not encrypt_key:
        raise ValueError("LARK_ENCRYPT_KEY is required for encrypted webhook payloads")
    return AESCipher(encrypt_key).decrypt_str(encrypted_text)


def _load_lark_payload(raw_body: bytes) -> dict[str, Any]:
    """
    解析飞书回调 JSON，并在需要时做解密

    @params:
        raw_body: 飞书回调原始请求体

    @return:
        返回统一的回调 JSON 字典
    """
    encrypt_key = (os.getenv("LARK_ENCRYPT_KEY") or "").strip()
    plaintext = _decrypt_lark_payload(raw_body, encrypt_key)
    return json.loads(plaintext)


def _extract_event_type(payload: dict[str, Any]) -> str:
    """
    提取飞书事件类型

    @params:
        payload: 已解析的飞书回调 JSON

    @return:
        返回事件类型字符串；无法识别时返回空字符串
    """
    return (
        payload.get("header", {}).get("event_type")
        or payload.get("type")
        or ""
    )


def _extract_verification_token(payload: dict[str, Any]) -> str:
    """
    提取飞书回调用于校验的 token

    @params:
        payload: 已解析的飞书回调 JSON

    @return:
        返回回调 token；无法识别时返回空字符串
    """
    return (
        payload.get("header", {}).get("token")
        or payload.get("token")
        or ""
    )


def _extract_event_id(payload: dict[str, Any]) -> str:
    """
    提取飞书事件 ID

    @params:
        payload: 已解析的飞书回调 JSON

    @return:
        返回事件 ID；v2 用 header.event_id，v1 回退到 uuid
    """
    return (
        payload.get("header", {}).get("event_id")
        or payload.get("uuid")
        or ""
    )


def _is_legacy_start_request(payload: dict[str, Any]) -> bool:
    """
    判断是否为旧版 start_demand 启动请求

    @params:
        payload: 已解析的请求 JSON

    @return:
        是旧版启动请求时返回 True，否则返回 False
    """
    return payload.get("action") == "start_demand" and not payload.get("header")


def _validate_lark_token(payload: dict[str, Any]) -> None:
    """
    校验飞书 verification token

    @params:
        payload: 已解析的飞书回调 JSON

    @return:
        校验通过时无返回；校验失败时抛出异常
    """
    expected_token = (os.getenv("LARK_VERIFICATION_TOKEN") or "").strip()
    if not expected_token:
        return

    token = _extract_verification_token(payload)
    if token != expected_token:
        raise ValueError("invalid verification token")


def _validate_lark_signature(request: Request, raw_body: bytes, payload: dict[str, Any]) -> None:
    """
    校验飞书回调签名

    @params:
        request: FastAPI 请求对象
        raw_body: 飞书回调原始请求体
        payload: 已解析的飞书回调 JSON

    @return:
        校验通过时无返回；校验失败时抛出异常
    """
    encrypt_key = (os.getenv("LARK_ENCRYPT_KEY") or "").strip()
    if not encrypt_key:
        return

    # URL 验证事件只需要通过 token 校验并回传 challenge，不要求验签
    if _extract_event_type(payload) == URL_VERIFICATION:
        return

    timestamp = request.headers.get(LARK_REQUEST_TIMESTAMP)
    nonce = request.headers.get(LARK_REQUEST_NONCE)
    signature = request.headers.get(LARK_REQUEST_SIGNATURE)
    if not timestamp or not nonce or not signature:
        raise ValueError("missing lark signature headers")

    expected_signature = hashlib.sha256(
        (timestamp + nonce + encrypt_key).encode("utf-8") + raw_body
    ).hexdigest()
    if signature != expected_signature:
        raise ValueError("signature verification failed")


def _launch_background_task(target: Callable[[], None]) -> None:
    """
    启动后台线程执行耗时逻辑

    @params:
        target: 需要在后台执行的无参函数

    @return:
        无返回值；函数会在守护线程中异步执行
    """
    threading.Thread(target=target, daemon=True).start()


def _resolve_requirement_text(doc_url: str) -> str:
    """
    根据文档链接或文本构造需求描述

    @params:
        doc_url: 启动请求中携带的文档链接或文本

    @return:
        返回传给 pipeline 的最终需求文本
    """
    if "feishu.cn" in doc_url or "larksuite.com" in doc_url:
        doc_content = fetch_lark_doc_content(doc_url)
        return (
            "请查阅此需求文档并进行技术方案设计：\n\n"
            f"【文档链接】\n{doc_url}\n\n"
            f"【文档内容】\n{doc_content}"
        )
    return f"请查阅此需求文档并进行技术方案设计：{doc_url}"


def _normalize_start_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """
    标准化 start_demand 请求中的 demand_id 与 doc_url

    @params:
        payload: 启动请求 JSON

    @return:
        返回标准化后的 demand_id 与 doc_url
    """
    demand_id = str(payload.get("demand_id", ""))
    doc_url = payload.get("doc_url", "")

    if isinstance(doc_url, list) and doc_url and isinstance(doc_url[0], dict):
        doc_url = doc_url[0].get("link", doc_url[0].get("text", ""))
    elif isinstance(doc_url, dict):
        doc_url = doc_url.get("link", doc_url.get("text", ""))

    doc_url = str(doc_url)
    if not demand_id or re.match(r"^\{\{.*\}\}$", demand_id):
        demand_id = f"DEMAND-{int(time.time())}"

    if not doc_url or re.match(r"^\{\{.*\}\}$", doc_url):
        doc_url = "未提供具体文档链接，请根据后续对话补充需求。"

    if doc_url in {"需求", "[{'text': '需求'}]"}:
        doc_url = "未提供具体文档链接，请根据后续对话补充需求。"

    return demand_id, doc_url


def _handle_start_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    处理启动新需求的入口请求

    @params:
        payload: 启动请求 JSON

    @return:
        返回启动成功的统一响应
    """
    demand_id, doc_url = _normalize_start_payload(payload)
    print(f"[Webhook] 收到启动请求，开始处理新需求: {demand_id}, 文档: {doc_url}")

    def run_start() -> None:
        from pipeline.engine import start_new_demand

        start_new_demand(demand_id, _resolve_requirement_text(doc_url))

    _launch_background_task(run_start)
    return {"code": 0, "msg": "success"}


def update_card_status(message: str) -> dict[str, Any]:
    """
    返回用于更新飞书卡片状态的 JSON

    @params:
        message: 需要展示在卡片中的状态文本

    @return:
        返回符合飞书卡片更新格式的 JSON 结构
    """
    return {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🚀 状态已更新",
            },
            "template": "green",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**{message}**",
            }
        ],
    }


@app.middleware("http")
async def validate_lark_webhook(request: Request, call_next: Callable[[Request], Any]):
    """
    对飞书 webhook 做统一校验与载荷标准化

    @params:
        request: 当前 FastAPI 请求对象
        call_next: 继续向下游路由传递请求的回调

    @return:
        返回后续路由响应；校验失败时直接返回 403
    """
    if request.method != "POST" or request.url.path != "/lark/webhook":
        return await call_next(request)

    raw_body = await request.body()
    try:
        payload = _load_lark_payload(raw_body)

        # 历史上这里承接过多维表格的裸 HTTP 触发；为了不破坏现有流量，继续兼容这种非事件请求
        if _is_legacy_start_request(payload):
            request.state.lark_payload = payload
            return await call_next(request)

        _validate_lark_token(payload)
        _validate_lark_signature(request, raw_body, payload)
        request.state.lark_payload = payload
        request.state.lark_event_id = _extract_event_id(payload)
    except Exception as exc:
        return JSONResponse(status_code=403, content={"code": 403, "msg": str(exc)})

    return await call_next(request)


@app.post("/start")
async def start_demand(request: Request):
    """
    兼容外部系统直接启动新需求

    @params:
        request: FastAPI 请求对象

    @return:
        返回启动结果 JSON
    """
    payload = await request.json()
    if payload.get("action") != "start_demand":
        return {"code": 400, "msg": "invalid start action"}
    return _handle_start_request(payload)


@app.post("/lark/webhook")
async def lark_webhook(request: Request):
    """
    接收飞书回调并驱动审批流恢复

    @params:
        request: FastAPI 请求对象

    @return:
        返回飞书要求的 challenge、卡片更新 JSON 或普通成功响应
    """
    payload = getattr(request.state, "lark_payload", None)
    if payload is None:
        payload = await request.json()

    if _extract_event_type(payload) == URL_VERIFICATION or "challenge" in payload:
        return {"challenge": payload.get("challenge", "")}

    if _is_legacy_start_request(payload):
        return _handle_start_request(payload)

    event_type = _extract_event_type(payload)
    if event_type and event_type != "card.action.trigger":
        print(f"[Webhook] 忽略非卡片点击事件: {event_type}")
        return {"code": 0, "msg": "ignored"}

    event_id = getattr(request.state, "lark_event_id", "") or _extract_event_id(payload)
    if event_id and not _remember_event_id(event_id):
        print(f"[Webhook] 忽略重复事件: {event_id}")
        return update_card_status("⏳ 请求已处理，请勿重复点击")

    action_data = payload.get("action") or payload.get("event", {}).get("action") or {}
    if isinstance(action_data, str):
        return {"code": 400, "msg": "unknown action format"}

    action_value = action_data.get("value", {})
    action_type = action_value.get("action")
    demand_id = action_value.get("demand_id")
    if not action_type or not demand_id:
        print(f"[Webhook] 收到无效的 action 数据: {payload}")
        return update_card_status(f"解析失败，收到的数据: {json.dumps(payload, ensure_ascii=False)}")

    if action_type == "approve":
        print(f"[Webhook] 需求 {demand_id} 已通过审批，准备进入 Coding 阶段...")

        def run_resume() -> None:
            time.sleep(1)
            from pipeline.engine import resume_after_approval

            resume_after_approval(
                demand_id,
                approved=True,
                feedback="人类已同意该设计方案。请进入 Phase 2: Coding 阶段，开始编写代码。",
            )

        _launch_background_task(run_resume)
        return update_card_status("✅ 已通过审批，AI 正在疯狂编码中...")

    if action_type == "reject":
        print(f"[Webhook] 需求 {demand_id} 被驳回，要求 AI 重新设计...")

        def run_reject() -> None:
            time.sleep(1)
            from pipeline.engine import resume_after_approval

            resume_after_approval(
                demand_id,
                approved=False,
                feedback="人类驳回了该方案。请重新检查需求并修改你的设计文档。",
            )

        _launch_background_task(run_reject)
        return update_card_status("❌ 已驳回，AI 正在重新设计...")

    return {"code": 400, "msg": f"unsupported action: {action_type}"}
