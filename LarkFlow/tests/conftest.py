"""共享 pytest fixture (A6)

为 A 系列测试提供统一的：
- 临时 SqliteSessionStore 替换 engine.STORE
- 替身 build_client 避免真实 SDK 初始化
- 隔离日志文件目录，避免污染 repo 根下的 logs/
"""
import logging
import tempfile
from pathlib import Path

import pytest

from pipeline.core import engine

from pipeline.ops import observability
from pipeline.core.persistence import SqliteSessionStore


@pytest.fixture
def temp_session_store(monkeypatch):
    """给 engine.STORE 打替身，返回该临时 store；函数结束自动清理。"""
    with tempfile.TemporaryDirectory(prefix="larkflow-fixture-") as tmp:
        store = SqliteSessionStore(str(Path(tmp) / "s.db"))
        monkeypatch.setattr(engine, "STORE", store)
        yield store


@pytest.fixture
def stub_build_client(monkeypatch):
    """避免 engine._load_session 触发真实 Anthropic/OpenAI SDK 初始化。"""
    monkeypatch.setattr(engine, "build_client", lambda provider: object())


@pytest.fixture
def isolated_log_file(monkeypatch, tmp_path):
    """把 observability 的日志文件重定向到临时目录。"""
    log_path = tmp_path / "larkflow.jsonl"
    monkeypatch.setenv("LARKFLOW_LOG_FILE", str(log_path))
    # 清掉已配置标志，强制下一次 get_logger 重新绑定 handler
    root = logging.getLogger("larkflow")
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
    observability._configured = False
    yield log_path
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
    observability._configured = False
