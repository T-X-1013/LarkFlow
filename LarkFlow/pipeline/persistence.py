"""会话持久化层 (A1)

提供 SessionStore 抽象与 SQLite 默认实现，替代 engine.py 中内存 dict 的
SESSION_STORE。支持进程重启恢复、多需求并发加锁，并为 A2 的阶段状态机预留
phase 列。
"""
from __future__ import annotations

import abc
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

# 序列化时需剥离的非 JSON 字段
# client: LLM SDK 对象，恢复时由 build_client(provider) 重建
# logger: A4 将注入的结构化 logger，恢复时由 get_logger(demand_id) 重建
_TRANSIENT_KEYS = ("client", "logger")


def _strip_transient(session: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in session.items() if k not in _TRANSIENT_KEYS}


class SessionStore(abc.ABC):
    """会话存储接口。实现需保证 save/get 原子、跨进程可见。"""

    @abc.abstractmethod
    def get(self, demand_id: str) -> Optional[Dict[str, Any]]:
        """按 demand_id 读取 session。不存在返回 None。返回值不含 transient 字段。"""

    @abc.abstractmethod
    def save(self, demand_id: str, session: Dict[str, Any]) -> None:
        """写入或覆盖 session。内部负责剥离 transient 字段后序列化。"""

    @abc.abstractmethod
    def delete(self, demand_id: str) -> None:
        ...

    @abc.abstractmethod
    def list_active(self) -> List[str]:
        """返回所有未进入终态 (done / failed) 的 demand_id。"""


class SqliteSessionStore(SessionStore):
    """SQLite 实现。连接按线程隔离，写操作串行化以避免 database is locked。"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS sessions (
        demand_id   TEXT PRIMARY KEY,
        phase       TEXT,
        payload     TEXT NOT NULL,
        updated_at  INTEGER NOT NULL
    )
    """

    _TERMINAL_PHASES = ("done", "failed")

    def __init__(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        # 提前建表
        with self._connect() as conn:
            conn.execute(self._SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, isolation_level=None, timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def get(self, demand_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT payload FROM sessions WHERE demand_id = ?", (demand_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def save(self, demand_id: str, session: Dict[str, Any]) -> None:
        payload = _strip_transient(session)
        phase = payload.get("phase")
        payload_text = json.dumps(payload, ensure_ascii=False, default=str)
        now = int(time.time())
        with self._write_lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO sessions (demand_id, phase, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(demand_id) DO UPDATE SET
                    phase = excluded.phase,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (demand_id, phase, payload_text, now),
            )

    def delete(self, demand_id: str) -> None:
        with self._write_lock:
            conn = self._connect()
            conn.execute("DELETE FROM sessions WHERE demand_id = ?", (demand_id,))

    def list_active(self) -> List[str]:
        conn = self._connect()
        placeholders = ",".join("?" for _ in self._TERMINAL_PHASES)
        rows = conn.execute(
            f"SELECT demand_id FROM sessions "
            f"WHERE phase IS NULL OR phase NOT IN ({placeholders}) "
            f"ORDER BY updated_at ASC",
            self._TERMINAL_PHASES,
        ).fetchall()
        return [r[0] for r in rows]


def default_store() -> SessionStore:
    """根据环境变量 LARKFLOW_SESSION_DB 构造默认 store。"""
    db_path = os.getenv("LARKFLOW_SESSION_DB", ".larkflow/sessions.db")
    return SqliteSessionStore(db_path)
