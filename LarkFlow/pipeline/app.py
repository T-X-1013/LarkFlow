"""LarkFlow 双入口：asyncio 并行 WS 长连 + FastAPI HTTP server。

Docker 入口：python -m pipeline.app
本地：python -m pipeline.app  或  uvicorn pipeline.app:app

WS (lark_interaction.run_event_loop) 内部跑 lark-oapi 的全局 asyncio loop，
SDK 未暴露 stop 接口，因此以 daemon 线程随进程退出；HTTP 端走 uvicorn
原生 should_exit 优雅关停。
"""
from __future__ import annotations

import asyncio
import logging
import signal
import threading
from typing import Optional

import uvicorn

from pipeline.config import runtime as runtime_config  # 触发 .env 加载
from pipeline.api import create_app
from pipeline.lark.interaction import run_event_loop

logger = logging.getLogger("larkflow.app")

# FastAPI app（供 uvicorn pipeline.app:app 直接引用）
app = create_app()


async def _run_http(host: str, port: int, stop_event: asyncio.Event) -> None:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=runtime_config.uvicorn_log_level(),
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    # 由外层统一处理 SIGINT/SIGTERM，避免与 main() 的 handler 互相覆盖；
    # uvicorn 的 Config 不接受 install_signal_handlers 参数，需覆盖 Server 方法
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    serve_task = asyncio.create_task(server.serve(), name="uvicorn-serve")

    async def _watch_stop() -> None:
        await stop_event.wait()
        server.should_exit = True

    watcher = asyncio.create_task(_watch_stop(), name="uvicorn-stop-watch")
    try:
        await serve_task
    finally:
        watcher.cancel()


async def _run_ws() -> None:
    """
    lark-oapi 的 ws.Client.start() 使用 SDK 模块级全局 loop 并阻塞在 _select()，
    没有公开的停止接口。用 daemon 线程承载，让它随主进程退出；线程内抛错时
    通过 Future 透传回主 loop，避免静默吞掉异常。
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()

    def _runner() -> None:
        try:
            run_event_loop()
        except BaseException as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(
                lambda: future.done() or future.set_exception(exc)
            )
        else:
            loop.call_soon_threadsafe(
                lambda: future.done() or future.set_result(None)
            )

    threading.Thread(target=_runner, daemon=True, name="lark-ws").start()

    try:
        await future
    except Exception:
        logger.exception("lark ws listener crashed")
        raise


async def main(host: Optional[str] = None, port: Optional[int] = None) -> None:
    resolved_host = host or runtime_config.http_host()
    resolved_port = int(port) if port else runtime_config.http_port()

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

    http_task = asyncio.create_task(
        _run_http(resolved_host, resolved_port, stop_event), name="http"
    )
    ws_task = asyncio.create_task(_run_ws(), name="ws")

    # 任一侧先退出（正常或异常）都要拉动另一侧一起下线
    done, _pending = await asyncio.wait(
        {http_task, ws_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    stop_event.set()

    # 等 HTTP 走完 uvicorn 的优雅关停；WS 是 daemon 线程，随进程死
    if not http_task.done():
        try:
            await http_task
        except Exception:
            logger.exception("http server exited with error")

    # 把先完成任务里的异常抛出来（如果有）
    for task in done:
        exc = task.exception()
        if exc:
            raise exc


if __name__ == "__main__":
    asyncio.run(main())
