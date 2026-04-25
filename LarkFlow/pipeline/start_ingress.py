"""
LarkFlow 启动需求专用 HTTP 入口

只负责接收多维表格自动化触发的 start_demand 请求：
1. 不承担飞书卡片点击、审批、事件订阅等职责
2. 仅做最小鉴权、JSON 解析与参数转发
3. 复用 lark_interaction.handle_start_request() 进入现有启动流程
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException

from pipeline.lark_interaction import handle_start_request

load_dotenv()

app = FastAPI(title="LarkFlow Start Ingress")


def _expected_token() -> str:
    return (os.getenv("LARK_START_INGRESS_TOKEN") or "").strip()


def _verify_token(provided_token: str | None) -> None:
    expected = _expected_token()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="LARK_START_INGRESS_TOKEN is not configured",
        )
    if (provided_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"code": 0, "msg": "ok"}


@app.post("/lark/start-demand")
def start_demand(
    payload: dict[str, Any],
    x_larkflow_token: str | None = Header(default=None, alias="X-LarkFlow-Token"),
) -> dict[str, Any]:
    _verify_token(x_larkflow_token)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid payload")
    return handle_start_request(payload)
