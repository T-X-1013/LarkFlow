import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.llm.tools_runtime import ToolContext, _build_mysql_connection_kwargs, execute


class InspectDbTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace_root = self.root / "workspace"
        self.target_dir = self.root / "demo-app"
        self.workspace_root.mkdir()
        self.target_dir.mkdir()

        self.ctx = ToolContext(
            demand_id="DEMAND-B3",
            workspace_root=str(self.workspace_root),
            target_dir=str(self.target_dir),
            logger=None,
        )

        self.sqlite_db_path = self.target_dir / "app.db"
        with sqlite3.connect(str(self.sqlite_db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO users (name, created_at) VALUES (?, ?)",
                ("alice", "2026-04-20"),
            )
            connection.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_db_requires_database_url(self):
        with patch.dict(os.environ, {}, clear=True):
            result = execute("inspect_db", {"query": "SHOW CREATE TABLE users"}, self.ctx)

        self.assertIn("DATABASE_URL is not configured", result)

    def test_inspect_db_returns_sqlite_show_create_table(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///demo-app/app.db"}, clear=True):
            result = execute("inspect_db", {"query": "SHOW CREATE TABLE users"}, self.ctx)

        self.assertIn("DATABASE: sqlite", result)
        self.assertIn("CREATE TABLE users", result)
        self.assertIn("QUERY: SELECT name, sql FROM sqlite_master", result)

    def test_inspect_db_returns_sqlite_select_rows(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///demo-app/app.db"}, clear=True):
            result = execute("inspect_db", {"query": "SELECT id, name FROM users LIMIT 1"}, self.ctx)

        self.assertIn("DATABASE: sqlite", result)
        self.assertIn("COLUMNS:", result)
        self.assertIn("- id", result)
        self.assertIn("- name", result)
        self.assertIn("name: alice", result)

    def test_inspect_db_rejects_non_read_only_query(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///demo-app/app.db"}, clear=True):
            result = execute("inspect_db", {"query": "DELETE FROM users"}, self.ctx)

        self.assertIn("inspect_db only supports read-only schema or select queries", result)

    def test_inspect_db_returns_clear_mysql_dependency_error(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "mysql://root:pass@127.0.0.1:3306/test_db"},
            clear=True,
        ), patch.dict("sys.modules", {"pymysql": None}):
            result = execute("inspect_db", {"query": "SHOW CREATE TABLE users"}, self.ctx)

        self.assertIn("PyMySQL is not installed", result)

    def test_build_mysql_connection_kwargs_supports_mysql_scheme(self):
        kwargs = _build_mysql_connection_kwargs("mysql://root:pass@127.0.0.1:3307/test_db")

        self.assertEqual(
            kwargs,
            {
                "host": "127.0.0.1",
                "port": 3307,
                "user": "root",
                "password": "pass",
                "database": "test_db",
                "charset": "utf8mb4",
            },
        )

    def test_build_mysql_connection_kwargs_supports_mysql_pymysql_scheme(self):
        kwargs = _build_mysql_connection_kwargs(
            "mysql+pymysql://user%40demo:pa%24%24@db.example.com:3306/larkflow_demo"
        )

        self.assertEqual(kwargs["host"], "db.example.com")
        self.assertEqual(kwargs["port"], 3306)
        self.assertEqual(kwargs["user"], "user@demo")
        self.assertEqual(kwargs["password"], "pa$$")
        self.assertEqual(kwargs["database"], "larkflow_demo")

    def test_inspect_db_executes_mysql_query_when_pymysql_is_available(self):
        captured = {}

        class FakeCursor:
            def __init__(self):
                self.description = (("id",), ("name",))
                self._rows = ((1, "alice"),)

            def execute(self, query):
                captured["query"] = query

            def fetchall(self):
                return self._rows

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def close(self):
                captured["closed"] = True

        def fake_connect(**kwargs):
            captured["kwargs"] = kwargs
            return FakeConnection()

        fake_pymysql = SimpleNamespace(
            connect=fake_connect,
            cursors=SimpleNamespace(Cursor=object),
        )

        with patch.dict(
            os.environ,
            {"DATABASE_URL": "mysql://root:pass@127.0.0.1:3306/test_db"},
            clear=True,
        ), patch.dict("sys.modules", {"pymysql": fake_pymysql}):
            result = execute("inspect_db", {"query": "SELECT id, name FROM users LIMIT 1"}, self.ctx)

        self.assertEqual(captured["query"], "SELECT id, name FROM users LIMIT 1")
        self.assertEqual(captured["kwargs"]["host"], "127.0.0.1")
        self.assertEqual(captured["kwargs"]["port"], 3306)
        self.assertEqual(captured["kwargs"]["user"], "root")
        self.assertEqual(captured["kwargs"]["password"], "pass")
        self.assertEqual(captured["kwargs"]["database"], "test_db")
        self.assertIn("DATABASE: mysql", result)
        self.assertIn("name: alice", result)
        self.assertTrue(captured["closed"])


if __name__ == "__main__":
    unittest.main()
