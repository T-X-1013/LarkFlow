"""LarkFlow 双入口：asyncio 并行 WS 长连 + FastAPI HTTP server。

Docker 入口：python -m pipeline.app
本地：python -m pipeline.app  或  uvicorn pipeline.app:app

WS (lark_interaction.run_event_loop) 是阻塞 IO，跑在 thread executor；
FastAPI 由 uvicorn.Server 以协程方式跑在同一个 event loop，共享进程状态。
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Optional

import uvicorn
from dotenv import load_dotenv

from pipeline.api import create_app
from pipeline.lark_interaction import run_event_loop

load_dotenv()

logger = logging.getLogger("larkflow.app")

# FastAPI app（供 uvicorn pipeline.app:app 直接引用）
app = create_app()


async def _run_http(host: str, port: int) -> None:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_ws() -> None:
    """WS 长连是阻塞调用，丢到默认 executor 避免阻塞 asyncio loop。"""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, run_event_loop)
    except Exception:  # noqa: BLE001
        logger.exception("lark ws listener crashed")
        raise


async def main(host: Optional[str] = None, port: Optional[int] = None) -> None:
    resolved_host = host or os.getenv("PIPELINE_HTTP_HOST", "0.0.0.0")
    resolved_port = int(port or os.getenv("PIPELINE_HTTP_PORT", "8000"))

    tasks = [
        asyncio.create_task(_run_http(resolved_host, resolved_port), name="http"),
        asyncio.create_task(_run_ws(), name="ws"),
    ]

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal() -> None:
        logger.info("received stop signal, shutting down")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    done, pending = await asyncio.wait(
        [*tasks, asyncio.create_task(stop_event.wait(), name="stop")],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in done:
        if task.get_name() == "stop":
            continue
        exc = task.exception()
        if exc:
            raise exc


if __name__ == "__main__":
    asyncio.run(main())
