import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from pipeline.tools_runtime import ToolContext, _build_mysql_connection_kwargs, execute
from tests.path_utils import project_root, repo_root


class InspectDbMySQLIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.database_url = (os.getenv("MYSQL_TEST_DATABASE_URL") or "").strip()
        if not self.database_url:
            self.skipTest("MYSQL_TEST_DATABASE_URL is not configured")

        try:
            import pymysql
        except ModuleNotFoundError as exc:
            self.skipTest(f"PyMySQL is not installed: {exc}")

        self.pymysql = pymysql
        self.connection = pymysql.connect(
            **_build_mysql_connection_kwargs(self.database_url),
            cursorclass=pymysql.cursors.Cursor,
            autocommit=True,
        )

        self.table_name = f"lf_inspectdb_{uuid4().hex[:10]}"
        self.ctx = ToolContext(
            demand_id="DEMAND-B3-MYSQL",
            workspace_root=str(project_root()),
            target_dir=str(repo_root() / "demo-app"),
            logger=None,
        )

        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE {self.table_name} (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(64) NOT NULL
                )
                """
            )
            cursor.execute(
                f"INSERT INTO {self.table_name} (name) VALUES (%s)",
                ("alice",),
            )

    def tearDown(self):
        connection = getattr(self, "connection", None)
        table_name = getattr(self, "table_name", None)

        if connection and table_name:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            finally:
                connection.close()

    def test_inspect_db_reads_real_mysql_schema_and_rows(self):
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=False):
            show_result = execute("inspect_db", {"query": f"SHOW CREATE TABLE {self.table_name}"}, self.ctx)
            select_result = execute(
                "inspect_db",
                {"query": f"SELECT id, name FROM {self.table_name} LIMIT 1"},
                self.ctx,
            )

        self.assertIn("DATABASE: mysql", show_result)
        self.assertIn("CREATE TABLE", show_result)
        self.assertIn(self.table_name, show_result)

        self.assertIn("DATABASE: mysql", select_result)
        self.assertIn("name: alice", select_result)


if __name__ == "__main__":
    unittest.main()
