"""
LarkFlow 飞书事件入口（WebSocket 长连模式）

负责：
1. 通过 lark-oapi SDK 的 WebSocket 客户端订阅飞书事件推送，无需公网可达
2. 对 event_id 做 24 小时幂等，避免重复点击或重复推送多次触发 pipeline
3. 处理卡片审批回调并唤醒对应的需求流程

SDK 已负责 URL 校验、verification token 校验、签名校验、加密解密，本文件只处理业务层事件。
"""

import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import lark_oapi as lark
import certifi
from dotenv import load_dotenv
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.api.drive.v1 import P2DriveFileBitableRecordChangedV1

from pipeline.lark_bitable_listener import (
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_REJECTED,
    on_record_changed,
    subscribe_demand_base,
    update_demand_status,
)
from pipeline.utils.lark_doc import LarkDocError, fetch_lark_doc_content
from pipeline.utils.lark_sdk import get_lark_client

load_dotenv()
os.environ.setdefault("SSL_CERT_FILE", certifi.where())


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
        try:
            doc_content = fetch_lark_doc_content(doc_url)
        except LarkDocError as exc:
            doc_content = f"[读取文档失败] {exc}"
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


def handle_start_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    处理启动新需求的入口请求

    @params:
        payload: 启动请求 JSON

    @return:
        返回启动结果 JSON
    """
    demand_id, doc_url = _normalize_start_payload(payload)
    print(f"[LarkListener] 收到启动请求，开始处理新需求: {demand_id}, 文档: {doc_url}")

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


def process_card_action(
    event_id: str,
    action_value: dict[str, Any],
) -> dict[str, Any]:
    """
    根据卡片按钮的 value 派发审批动作

    @params:
        event_id: 飞书事件 ID，用于 24h 幂等去重
        action_value: 卡片按钮的 value 字典，含 action / demand_id

    @return:
        返回用于回写卡片的 JSON 结构（update_card_status 风格）
    """
    if event_id and not _remember_event_id(event_id):
        print(f"[LarkListener] 忽略重复事件: {event_id}")
        return update_card_status("⏳ 请求已处理，请勿重复点击")

    action_type = None
    demand_id = None
    if isinstance(action_value, dict):
        action_type = action_value.get("action_type") or action_value.get("action")
        demand_id = action_value.get("demand_id")

    if not action_type:
        print(f"[LarkListener] 收到无效的 action 数据: {action_value}")
        return update_card_status(f"解析失败，收到的数据: {action_value}")

    if not demand_id:
        print(f"[LarkListener] 收到缺少 demand_id 的 action 数据: {action_value}")
        return update_card_status(f"解析失败，收到的数据: {action_value}")

    if action_type == "approve":
        print(f"[LarkListener] 需求 {demand_id} 已通过审批，准备进入 Coding 阶段...")

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
        print(f"[LarkListener] 需求 {demand_id} 被驳回，要求 AI 重新设计...")

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

    if action_type == "start_demand":
        # 方案 B：Base 新增需求行后发送的启动审批卡片点击「开始处理」
        record_id = action_value.get("record_id") if isinstance(action_value, dict) else None
        doc_url = action_value.get("doc_url", "") if isinstance(action_value, dict) else ""
        print(f"[LarkListener] 启动新需求: demand_id={demand_id} record={record_id}")

        if record_id and not update_demand_status(record_id, STATUS_PROCESSING):
            # 回写失败不阻止流程推进，但给卡片一个明确的告警
            print(f"[LarkListener] 记录 {record_id} 状态回写「处理中」失败，继续启动")

        try:
            handle_start_request({"demand_id": demand_id, "doc_url": doc_url})
        except Exception as exc:  # noqa: BLE001
            print(f"[LarkListener] 启动需求失败 demand_id={demand_id}: {exc}")
            if record_id:
                update_demand_status(record_id, STATUS_FAILED)
            return update_card_status(f"❌ 启动失败: {exc}")
        return update_card_status(f"🚀 已开始处理需求 {demand_id}")

    if action_type == "reject_demand":
        record_id = action_value.get("record_id") if isinstance(action_value, dict) else None
        print(f"[LarkListener] 需求 {demand_id} 在启动前被驳回 record={record_id}")
        if record_id:
            update_demand_status(record_id, STATUS_REJECTED)
        return update_card_status(f"❌ 已驳回需求 {demand_id}")

    return update_card_status(f"unsupported action: {action_type}")


def _on_card_action(event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """
    SDK WebSocket 通道收到卡片点击事件时的回调

    @params:
        event: SDK 解析好的 P2CardActionTrigger 事件对象

    @return:
        返回 P2CardActionTriggerResponse，包含要更新的卡片内容
    """
    event_id = (
        event.header.event_id if event.header and event.header.event_id else ""
    )
    action_value = (
        event.event.action.value if event.event and event.event.action else {}
    ) or {}

    card_json = process_card_action(event_id, action_value)
    return P2CardActionTriggerResponse(
        {"card": {"type": "raw", "data": card_json}}
    )


def _on_bitable_record_changed(event: P2DriveFileBitableRecordChangedV1) -> None:
    """
    Base 记录变更事件的 WS 回调壳；实际业务在 lark_bitable_listener 内处理

    @params:
        event: SDK 解析好的事件对象

    @return:
        无返回值
    """
    on_record_changed(event)


def _build_event_handler() -> "lark.EventDispatcherHandler":
    """
    构建 lark-oapi 事件分发 handler，注册卡片点击 + Base 记录变更回调

    @params:
        无入参

    @return:
        返回已注册好事件回调的 EventDispatcherHandler
    """
    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(_on_card_action)
        .register_p2_drive_file_bitable_record_changed_v1(_on_bitable_record_changed)
        .build()
    )


def run_event_loop(app_id: Optional[str] = None, app_secret: Optional[str] = None) -> None:
    """
    启动 lark-oapi WebSocket 长连，阻塞式监听飞书事件

    @params:
        app_id: 飞书应用 ID；为空时读取 LARK_APP_ID 环境变量
        app_secret: 飞书应用 secret；为空时读取 LARK_APP_SECRET 环境变量

    @return:
        无返回值；函数会阻塞直到连接终止
    """
    # 同样必须 strip，docker --env-file 不会自动 trim 尾部空白
    resolved_app_id = (app_id or os.getenv("LARK_APP_ID") or "").strip().strip('"').strip("'")
    resolved_app_secret = (app_secret or os.getenv("LARK_APP_SECRET") or "").strip().strip('"').strip("'")
    if not resolved_app_id or not resolved_app_secret:
        raise RuntimeError(
            "缺少 LARK_APP_ID 或 LARK_APP_SECRET 环境变量，无法启动飞书事件监听"
        )

    # 预热共享 Client，保证出站消息与入站事件共用同一份 token 缓存
    get_lark_client()

    # 幂等订阅需求 Base 的文件事件；未配置 BASE_TOKEN 时 listener 内部会跳过
    subscribe_demand_base()

    ws_client = lark.ws.Client(
        resolved_app_id,
        resolved_app_secret,
        event_handler=_build_event_handler(),
        log_level=lark.LogLevel.INFO,
    )
    print("[LarkListener] WebSocket 长连已启动，等待飞书事件...")
    ws_client.start()


if __name__ == "__main__":
    run_event_loop()
