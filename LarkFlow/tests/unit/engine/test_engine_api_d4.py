"""D4 provider 切换与 metrics 聚合测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline import engine, engine_api, engine_control
from pipeline.api.routes import create_app
from pipeline.persistence import SqliteSessionStore


class EngineApiD4TestCase(unittest.TestCase):
    def setUp(self):
        """
        为每个用例准备隔离的 SessionStore 和空的控制注册表。

        @params:
            无

        @return:
            无返回值；把 engine.STORE 和 engine_control._REGISTRY 切到临时测试态
        """
        self._db_tmp = tempfile.TemporaryDirectory(prefix="larkflow-d4-api-")
        self._orig_store = engine.STORE
        self._orig_registry = dict(engine_control._REGISTRY)
        engine.STORE = SqliteSessionStore(str(Path(self._db_tmp.name) / "s.db"))
        engine_control._REGISTRY.clear()

    def tearDown(self):
        """
        恢复原始 SessionStore 和控制注册表。

        @params:
            无

        @return:
            无返回值；清理临时目录并还原全局状态
        """
        engine.STORE = self._orig_store
        engine_control._REGISTRY.clear()
        engine_control._REGISTRY.update(self._orig_registry)
        self._db_tmp.cleanup()

    def test_set_provider_normalizes_before_start(self):
        """启动前修改 provider 时，应先完成归一化再写入控制态"""
        state = engine_api.create_pipeline("demo")

        updated = engine_api.set_provider(state.id, " OpenAI ")

        self.assertEqual(updated.provider, "openai")
        self.assertEqual(engine_control.require(state.id).provider, "openai")

    def test_set_provider_rejects_unknown_provider(self):
        """未知 provider 应被 facade 直接拒绝"""
        state = engine_api.create_pipeline("demo")

        with self.assertRaises(ValueError):
            engine_api.set_provider(state.id, "unknown")

    def test_set_provider_rejects_pipeline_after_session_created(self):
        """一旦 session 已创建，就不允许再修改 provider，避免运行中切换模型"""
        state = engine_api.create_pipeline("demo")
        engine.STORE.save(state.id, {"demand_id": state.id, "provider": "anthropic"})

        with self.assertRaises(RuntimeError):
            engine_api.set_provider(state.id, "openai")

    def test_start_new_demand_uses_provider_selected_via_rest(self):
        """REST 侧设置的 provider 应真正传递到 engine 启动链路中"""
        state = engine_api.create_pipeline("demo")
        engine_api.set_provider(state.id, "openai")

        with patch.object(engine, "_ensure_target_scaffold"), patch.object(
            engine, "_run_phase", return_value=False
        ), patch.object(engine, "build_client", side_effect=lambda provider: object()):
            engine.start_new_demand(state.id, "demo")

        session = engine.STORE.get(state.id)
        self.assertEqual(session["provider"], "openai")
        self.assertEqual(engine_control.require(state.id).provider, "openai")

    def test_list_metrics_reads_real_session_aggregates(self):
        """metrics 接口应优先读取真实 session 中累计好的指标数据"""
        state = engine_api.create_pipeline("demo")
        engine.STORE.save(
            state.id,
            {
                "demand_id": state.id,
                "phase": "coding",
                "stage_results": {
                    "design": {
                        "stage": "design",
                        "status": "success",
                        "artifact_path": "https://example.com/design",
                        "tokens": {"input": 50, "output": 20},
                        "duration_ms": 1000,
                        "errors": [],
                    }
                },
                "metrics": {
                    "tokens_input": 321,
                    "tokens_output": 123,
                    "duration_ms": 4567,
                },
            },
        )

        items = engine_api.list_metrics()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].pipeline_id, state.id)
        self.assertEqual(items[0].tokens.input, 321)
        self.assertEqual(items[0].tokens.output, 123)
        self.assertEqual(items[0].duration_ms, 4567)
        self.assertIn("design", {stage.value for stage in items[0].stages})

    def test_list_metrics_falls_back_to_stage_totals_when_aggregate_missing(self):
        """聚合字段缺失时，应从 stage_results 回退出 tokens 和 duration"""
        state = engine_api.create_pipeline("demo")
        engine.STORE.save(
            state.id,
            {
                "demand_id": state.id,
                "phase": "reviewing",
                "stage_results": {
                    "design": {
                        "stage": "design",
                        "status": "success",
                        "artifact_path": None,
                        "tokens": {"input": 11, "output": 7},
                        "duration_ms": 800,
                        "errors": [],
                    },
                    "coding": {
                        "stage": "coding",
                        "status": "success",
                        "artifact_path": None,
                        "tokens": {"input": 19, "output": 13},
                        "duration_ms": 1200,
                        "errors": [],
                    },
                },
                "metrics": {},
            },
        )

        items = engine_api.list_metrics()

        self.assertEqual(items[0].tokens.input, 30)
        self.assertEqual(items[0].tokens.output, 20)
        self.assertEqual(items[0].duration_ms, 2000)

    def test_list_metrics_sorts_by_updated_at_desc(self):
        """metrics 列表应稳定按最新更新时间降序返回，方便前端首屏展示"""
        older = engine_api.create_pipeline("older")
        newer = engine_api.create_pipeline("newer")

        older_ctl = engine_control.require(older.id)
        newer_ctl = engine_control.require(newer.id)
        older_ctl.updated_at = 100
        newer_ctl.updated_at = 200

        items = engine_api.list_metrics()

        self.assertEqual([item.pipeline_id for item in items], [newer.id, older.id])

    def test_provider_route_maps_validation_errors_to_http_status(self):
        """HTTP 路由层应把 provider 校验错误映射成稳定的状态码"""
        app = create_app()
        client = TestClient(app)
        state = engine_api.create_pipeline("demo")

        bad = client.put(f"/pipelines/{state.id}/provider", json={"provider": "unknown"})
        self.assertEqual(bad.status_code, 400)

        engine.STORE.save(state.id, {"demand_id": state.id, "provider": "anthropic"})
        conflict = client.put(f"/pipelines/{state.id}/provider", json={"provider": "openai"})
        self.assertEqual(conflict.status_code, 409)
