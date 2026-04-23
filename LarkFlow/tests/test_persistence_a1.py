"""A1 持久化层单元测试"""
import os
import tempfile
import threading
import unittest
from pathlib import Path

from pipeline.persistence import SqliteSessionStore, default_store


class SqliteSessionStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="larkflow-persist-")
        self.db_path = str(Path(self._tmp.name) / "sessions.db")
        self.store = SqliteSessionStore(self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get("NOPE"))

    def test_save_then_get_roundtrip(self):
        session = {
            "provider": "openai",
            "history": [{"role": "user", "content": "hi"}],
            "phase": "design",
            "target_dir": "/tmp/demo",
        }
        self.store.save("D1", session)
        got = self.store.get("D1")
        self.assertEqual(got["history"], session["history"])
        self.assertEqual(got["phase"], "design")

    def test_save_strips_transient_fields(self):
        """client / logger 属于 transient，持久化时必须剥离"""
        session = {
            "provider": "openai",
            "client": object(),  # SDK 对象不可序列化
            "logger": object(),
            "history": [],
            "phase": "coding",
        }
        self.store.save("D2", session)
        got = self.store.get("D2")
        self.assertNotIn("client", got)
        self.assertNotIn("logger", got)
        self.assertEqual(got["phase"], "coding")

    def test_save_upserts(self):
        self.store.save("D3", {"phase": "design", "n": 1})
        self.store.save("D3", {"phase": "coding", "n": 2})
        got = self.store.get("D3")
        self.assertEqual(got["phase"], "coding")
        self.assertEqual(got["n"], 2)

    def test_delete(self):
        self.store.save("D4", {"phase": "design"})
        self.store.delete("D4")
        self.assertIsNone(self.store.get("D4"))

    def test_list_active_excludes_terminal(self):
        self.store.save("A", {"phase": "design"})
        self.store.save("B", {"phase": "coding"})
        self.store.save("C", {"phase": "done"})
        self.store.save("D", {"phase": "failed"})
        self.store.save("E", {})  # phase 缺失也算 active
        active = set(self.store.list_active())
        self.assertEqual(active, {"A", "B", "E"})

    def test_survives_process_restart(self):
        """同一 db 文件的新 store 实例能读到旧数据 → 模拟进程重启恢复"""
        self.store.save("D5", {"phase": "design", "history": [1, 2, 3]})
        reborn = SqliteSessionStore(self.db_path)
        got = reborn.get("D5")
        self.assertEqual(got["history"], [1, 2, 3])

    def test_concurrent_saves_no_corruption(self):
        """多线程并发写不同 demand，最终全部落盘"""
        def worker(i):
            self.store.save(f"DEM-{i}", {"phase": "design", "i": i})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        active = self.store.list_active()
        self.assertEqual(len(active), 20)


class DefaultStoreTestCase(unittest.TestCase):
    def test_default_store_honors_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "custom.db")
            os.environ["LARKFLOW_SESSION_DB"] = db_path
            try:
                store = default_store()
                store.save("X", {"phase": "design"})
                self.assertTrue(Path(db_path).exists())
            finally:
                os.environ.pop("LARKFLOW_SESSION_DB", None)


if __name__ == "__main__":
    unittest.main()
