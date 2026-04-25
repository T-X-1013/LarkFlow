"""A4 结构化日志与指标单元测试"""
import importlib
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from pipeline import observability


class ObservabilityA4TestCase(unittest.TestCase):
    def setUp(self):
        # 清空 logger handler 与配置状态，保证每个用例独立
        logger = logging.getLogger("larkflow")
        logger.handlers.clear()
        observability._configured = False

        self._tmp = tempfile.TemporaryDirectory(prefix="larkflow-logs-")
        self.log_path = str(Path(self._tmp.name) / "larkflow.jsonl")
        os.environ["LARKFLOW_LOG_FILE"] = self.log_path

    def tearDown(self):
        os.environ.pop("LARKFLOW_LOG_FILE", None)
        logger = logging.getLogger("larkflow")
        for h in list(logger.handlers):
            h.close()
        logger.handlers.clear()
        observability._configured = False
        self._tmp.cleanup()

    def _read_log_lines(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_logger_emits_json_with_demand_id(self):
        log = observability.get_logger("DEMAND-X", phase="coding")
        log.info("hello", extra={"event": "test_event"})

        lines = self._read_log_lines()
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertEqual(entry["demand_id"], "DEMAND-X")
        self.assertEqual(entry["phase"], "coding")
        self.assertEqual(entry["event"], "test_event")
        self.assertEqual(entry["message"], "hello")
        self.assertEqual(entry["level"], "INFO")

    def test_caller_extra_overrides_adapter_phase(self):
        """调用时的 phase 应覆盖 adapter 预置的 phase，支持临时切阶段打点"""
        log = observability.get_logger("D1", phase="design")
        log.info("msg", extra={"phase": "coding"})
        entry = self._read_log_lines()[0]
        self.assertEqual(entry["phase"], "coding")

    def test_log_turn_metrics_records_usage(self):
        log = observability.get_logger("D2", phase="coding")
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "latency_ms": 1200,
        }
        observability.log_turn_metrics(log, "coding", usage, tool_name="file_editor")

        entry = self._read_log_lines()[0]
        self.assertEqual(entry["event"], "agent_turn")
        self.assertEqual(entry["tokens_in"], 100)
        self.assertEqual(entry["tokens_out"], 50)
        self.assertEqual(entry["total_tokens"], 150)
        self.assertEqual(entry["latency_ms"], 1200)
        self.assertEqual(entry["tool_name"], "file_editor")

    def test_accumulate_metrics_sums_across_turns(self):
        session = {}
        observability.accumulate_metrics(session, {
            "prompt_tokens": 10, "completion_tokens": 20,
            "total_tokens": 30, "latency_ms": 500,
        })
        observability.accumulate_metrics(session, {
            "prompt_tokens": 5, "completion_tokens": 15,
            "total_tokens": 20, "latency_ms": 300,
        })
        m = session["metrics"]
        self.assertEqual(m["turns"], 2)
        self.assertEqual(m["tokens_in"], 15)
        self.assertEqual(m["tokens_out"], 35)
        self.assertEqual(m["total_tokens"], 50)
        self.assertEqual(m["latency_ms"], 800)

    def test_accumulate_metrics_tolerates_empty_usage(self):
        session = {}
        observability.accumulate_metrics(session, {})
        self.assertEqual(session["metrics"]["turns"], 1)
        self.assertEqual(session["metrics"]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
