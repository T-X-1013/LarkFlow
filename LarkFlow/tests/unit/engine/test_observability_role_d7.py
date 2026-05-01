"""D7 Step 5: observability role 维度单测。

覆盖：
- `get_logger(demand_id, phase, role=...)` 把 role 写入 extra，最终出现在 JSON 日志
- `get_logger` 不传 role 时 JSON 日志里不含 role 字段（向后兼容）
- `log_turn_metrics(..., role=...)` 把 role 带入 agent_turn 事件
- `parent_demand_id` 同样作为结构化字段透传
- `role` 字段通过 `_STD_EXTRA_KEYS` 白名单被 `_JsonFormatter` 吃掉
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from pipeline import observability


class ObservabilityRoleTestCase(unittest.TestCase):
    def setUp(self):
        logger = logging.getLogger("larkflow")
        logger.handlers.clear()
        observability._configured = False
        self._tmp = tempfile.TemporaryDirectory(prefix="larkflow-role-logs-")
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

    def test_role_is_in_std_extra_keys_whitelist(self):
        self.assertIn("role", observability._STD_EXTRA_KEYS)
        self.assertIn("parent_demand_id", observability._STD_EXTRA_KEYS)

    def test_logger_with_role_emits_role_field(self):
        log = observability.get_logger(
            "D42::review::security",
            phase="reviewing",
            role="security",
            parent_demand_id="D42",
        )
        log.info("sub reviewer tick", extra={"event": "agent_thinking"})

        entry = self._read_log_lines()[0]
        self.assertEqual(entry["role"], "security")
        self.assertEqual(entry["parent_demand_id"], "D42")
        self.assertEqual(entry["demand_id"], "D42::review::security")
        self.assertEqual(entry["phase"], "reviewing")

    def test_logger_without_role_omits_role_field(self):
        """向后兼容：非子 reviewer 路径不应出现空 role 字段。"""
        log = observability.get_logger("D1", phase="design")
        log.info("parent tick", extra={"event": "agent_thinking"})

        entry = self._read_log_lines()[0]
        self.assertNotIn("role", entry)
        self.assertNotIn("parent_demand_id", entry)

    def test_log_turn_metrics_with_role(self):
        log = observability.get_logger(
            "D42::review::testing-coverage",
            phase="reviewing",
            role="testing-coverage",
            parent_demand_id="D42",
        )
        usage = {
            "prompt_tokens": 200,
            "completion_tokens": 80,
            "total_tokens": 280,
            "latency_ms": 1500,
        }
        observability.log_turn_metrics(
            log,
            "reviewing",
            usage,
            tool_name="file_editor",
            role="testing-coverage",
        )

        entry = self._read_log_lines()[0]
        self.assertEqual(entry["event"], "agent_turn")
        self.assertEqual(entry["role"], "testing-coverage")
        self.assertEqual(entry["tokens_input"], 200)
        self.assertEqual(entry["tokens_output"], 80)

    def test_log_turn_metrics_without_role(self):
        """log_turn_metrics 不传 role 时，JSON 日志不应出现 role 字段。"""
        log = observability.get_logger("D_solo", phase="coding")
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "latency_ms": 50}
        observability.log_turn_metrics(log, "coding", usage, tool_name=None)

        entry = self._read_log_lines()[0]
        self.assertNotIn("role", entry)

    def test_role_from_adapter_not_duplicated_when_also_in_call_extra(self):
        """role 同时来自 adapter 和 call-site extra 时，call extra 覆盖 adapter（与现有 phase 行为一致）。"""
        log = observability.get_logger("D1", phase="reviewing", role="security")
        log.info("tick", extra={"event": "agent_thinking", "role": "overridden"})
        entry = self._read_log_lines()[0]
        self.assertEqual(entry["role"], "overridden")


if __name__ == "__main__":
    unittest.main()
