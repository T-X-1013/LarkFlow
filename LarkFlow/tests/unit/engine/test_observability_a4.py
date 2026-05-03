"""A4 结构化日志与指标单元测试"""
import importlib
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from pipeline import observability
from pipeline.contracts import PipelineState, PipelineStatus, Stage, StageResult, StageStatus


class ObservabilityA4TestCase(unittest.TestCase):
    def setUp(self):
        """
        为每个用例准备独立的临时日志文件和干净 logger 状态。

        @params:
            无

        @return:
            无返回值；重置 logger handler，并把日志输出重定向到临时文件
        """
        # 清空 logger handler 与配置状态，保证每个用例独立
        logger = logging.getLogger("larkflow")
        logger.handlers.clear()
        observability._configured = False

        self._tmp = tempfile.TemporaryDirectory(prefix="larkflow-logs-")
        self.log_path = str(Path(self._tmp.name) / "larkflow.jsonl")
        os.environ["LARKFLOW_LOG_FILE"] = self.log_path

    def tearDown(self):
        """
        清理临时日志文件和 logger 状态。

        @params:
            无

        @return:
            无返回值；关闭 handler 并释放临时目录
        """
        os.environ.pop("LARKFLOW_LOG_FILE", None)
        logger = logging.getLogger("larkflow")
        for h in list(logger.handlers):
            h.close()
        logger.handlers.clear()
        observability._configured = False
        self._tmp.cleanup()

    def _read_log_lines(self):
        """
        读取测试过程中产生的 JSON 日志行。

        @params:
            无

        @return:
            返回按行解析后的日志对象列表
        """
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_logger_emits_json_with_demand_id(self):
        """验证基础结构化日志会带上 demand_id、phase 和 event 等上下文字段"""
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
        """验证单轮 usage 会被展开成前端和旧脚本都能消费的指标字段"""
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
        self.assertEqual(entry["tokens_input"], 100)
        self.assertEqual(entry["tokens_output"], 50)
        self.assertEqual(entry["duration_ms"], 1200)
        self.assertEqual(entry["tokens_in"], 100)
        self.assertEqual(entry["tokens_out"], 50)
        self.assertEqual(entry["total_tokens"], 150)
        self.assertEqual(entry["latency_ms"], 1200)
        self.assertEqual(entry["tool_name"], "file_editor")

    def test_llm_events_record_provider_model_and_retry_fields(self):
        """验证 LLM 开始、重试、结束三类事件的字段约定保持稳定"""
        # 这里单独验证 LLM 事件 schema，避免后续改日志字段时只改了实现、忘了同步查询约定。
        log = observability.get_logger("D3", phase="coding")
        observability.log_llm_call_started(log, "coding", "openai", "gpt-5-codex")
        observability.log_llm_retry(
            log,
            "coding",
            "openai",
            "gpt-5-codex",
            "request failed",
            attempt=1,
            max_retries=3,
            wait_seconds=2.5,
        )
        observability.log_llm_call_finished(
            log,
            "coding",
            "openai",
            "gpt-5-codex",
            {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
                "latency_ms": 340,
            },
            finished=True,
            tool_call_count=0,
        )

        lines = self._read_log_lines()
        self.assertEqual(lines[0]["event"], "llm_call_start")
        self.assertEqual(lines[0]["provider"], "openai")
        self.assertEqual(lines[0]["model"], "gpt-5-codex")

        self.assertEqual(lines[1]["event"], "llm_retry")
        self.assertEqual(lines[1]["reason"], "request failed")
        self.assertEqual(lines[1]["attempt"], 1)
        self.assertEqual(lines[1]["max_retries"], 3)
        self.assertEqual(lines[1]["wait_seconds"], 2.5)

        self.assertEqual(lines[2]["event"], "llm_call_end")
        self.assertEqual(lines[2]["tokens_input"], 12)
        self.assertEqual(lines[2]["tokens_output"], 8)
        self.assertEqual(lines[2]["duration_ms"], 340)
        self.assertEqual(lines[2]["finished"], True)
        self.assertEqual(lines[2]["tool_call_count"], 0)

    def test_accumulate_metrics_sums_across_turns(self):
        """验证多轮调用的 usage 会正确累加到 session metrics"""
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
        # 新旧字段同时断言，确保历史聚合脚本和新的可观测性面板口径都不会被回归打断。
        self.assertEqual(m["turns"], 2)
        self.assertEqual(m["tokens_input"], 15)
        self.assertEqual(m["tokens_output"], 35)
        self.assertEqual(m["tokens_in"], 15)
        self.assertEqual(m["tokens_out"], 35)
        self.assertEqual(m["total_tokens"], 50)
        self.assertEqual(m["duration_ms"], 800)
        self.assertEqual(m["latency_ms"], 800)

    def test_accumulate_metrics_tolerates_empty_usage(self):
        """空 usage 不应导致异常，也不应把累计字段写成非法值"""
        session = {}
        observability.accumulate_metrics(session, {})
        self.assertEqual(session["metrics"]["turns"], 1)
        self.assertEqual(session["metrics"]["total_tokens"], 0)

    def test_accumulate_metrics_backfills_partial_metrics(self):
        """历史 session 或子 session 的不完整 metrics 应自动补齐字段"""
        session = {"metrics": {"tokens_input": 2, "tokens_output": 3}}
        observability.accumulate_metrics(session, {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "total_tokens": 12,
            "latency_ms": 90,
        })
        self.assertEqual(session["metrics"]["turns"], 1)
        self.assertEqual(session["metrics"]["tokens_input"], 7)
        self.assertEqual(session["metrics"]["tokens_output"], 10)
        self.assertEqual(session["metrics"]["tokens_in"], 5)
        self.assertEqual(session["metrics"]["tokens_out"], 7)
        self.assertEqual(session["metrics"]["total_tokens"], 12)
        self.assertEqual(session["metrics"]["duration_ms"], 90)

    def test_build_metrics_item_uses_session_metrics_and_stage_snapshot(self):
        """验证构建指标项时会优先使用 session 聚合数据并保留阶段快照"""
        state = PipelineState(
            id="P1",
            requirement="req",
            status=PipelineStatus.RUNNING,
            current_stage=Stage.CODING,
            stages={
                Stage.DESIGN: StageResult(
                    stage=Stage.DESIGN,
                    status=StageStatus.SUCCESS,
                    artifact_path="https://example.com/design",
                    duration_ms=1200,
                )
            },
        )
        item = observability.build_metrics_item(
            "P1",
            state,
            {
                "metrics": {
                    "tokens_input": 123,
                    "tokens_output": 45,
                    "duration_ms": 6789,
                }
            },
        )

        self.assertEqual(item.pipeline_id, "P1")
        self.assertEqual(item.status, PipelineStatus.RUNNING)
        self.assertEqual(item.tokens.input, 123)
        self.assertEqual(item.tokens.output, 45)
        self.assertEqual(item.duration_ms, 6789)
        self.assertEqual(item.stages[Stage.DESIGN].status, StageStatus.SUCCESS)

    def test_build_metrics_item_tolerates_missing_and_broken_metrics(self):
        """验证 metrics 缺失或格式不完整时，构建逻辑仍能安全退化到 0 值"""
        state = PipelineState(
            id="P2",
            requirement="req",
            status=PipelineStatus.PENDING,
        )
        item = observability.build_metrics_item(
            "P2",
            state,
            {
                "metrics": {
                    "tokens_input": "oops",
                    "tokens_output": None,
                    "duration_ms": "bad",
                }
            },
        )

        self.assertEqual(item.tokens.input, 0)
        self.assertEqual(item.tokens.output, 0)
        self.assertEqual(item.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
