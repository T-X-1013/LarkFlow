"""
飞书 SDK 连通性冒烟脚本

三级验证：
  level=auth   -> 调 bot info API，验证 app_id/secret 与网络可达
  level=send   -> 向 LARK_CHAT_ID 发送一条文本消息
  level=ws     -> 启动 WebSocket 长连，收到第一个事件即退出

用法:
  python scripts/smoke_lark_sdk.py auth
  python scripts/smoke_lark_sdk.py send "hello from LarkFlow SDK"
  python scripts/smoke_lark_sdk.py ws
"""

import os
import sys
import threading
import time

from dotenv import load_dotenv

load_dotenv()

from pipeline.lark.client import send_lark_text  # noqa: E402
from pipeline.lark.sdk import get_lark_client  # noqa: E402


def level_auth() -> int:
    """调 bot.v3 info，验证 app_id/secret、网络与基础 scope（多数应用默认具备）"""
    import lark_oapi as lark

    client = get_lark_client()
    raw = (
        lark.BaseRequest.builder()
        .http_method(lark.HttpMethod.GET)
        .uri("/open-apis/bot/v3/info")
        .token_types({lark.AccessTokenType.TENANT})
        .build()
    )
    resp = client.request(raw)
    if not resp.raw or not resp.raw.content:
        print("[auth] FAIL: empty response")
        return 1
    import json as _json
    body = _json.loads(resp.raw.content)
    if body.get("code") != 0:
        print(f"[auth] FAIL code={body.get('code')} msg={body.get('msg')}")
        return 1
    bot = body.get("bot") or {}
    print(f"[auth] OK bot_name={bot.get('app_name')} open_id={bot.get('open_id')}")
    return 0


def level_send(text: str) -> int:
    target = os.getenv("LARK_CHAT_ID")
    if not target:
        print("[send] FAIL: LARK_CHAT_ID 未配置")
        return 1
    result = send_lark_text(target, text)
    print(f"[send] result={result}")
    return 0 if result.get("code") == 0 else 1


def level_ws() -> int:
    import lark_oapi as lark
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTrigger,
        P2CardActionTriggerResponse,
    )

    got_event = threading.Event()

    def on_card(event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        print(f"[ws] received card.action.trigger event_id={event.header.event_id}")
        got_event.set()
        return P2CardActionTriggerResponse({"toast": {"type": "success", "content": "ok"}})

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(on_card)
        .build()
    )
    ws = lark.ws.Client(
        os.getenv("LARK_APP_ID"),
        os.getenv("LARK_APP_SECRET"),
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )

    t = threading.Thread(target=ws.start, daemon=True)
    t.start()
    print("[ws] WebSocket 已启动，60s 内点击飞书里任意已发送的卡片按钮以验证收包；Ctrl+C 退出")
    try:
        for _ in range(60):
            if got_event.wait(1):
                print("[ws] OK 收到事件，长连通路 ✅")
                return 0
    except KeyboardInterrupt:
        print("[ws] 用户中断")
    print("[ws] 60s 内未收到卡片事件；如果无人点击这是正常的，能看到 'Connected' 日志就说明长连已建立")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    level = sys.argv[1]
    if level == "auth":
        return level_auth()
    if level == "send":
        text = sys.argv[2] if len(sys.argv) > 2 else "hello from LarkFlow SDK"
        return level_send(text)
    if level == "ws":
        return level_ws()
    print(f"unknown level: {level}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
