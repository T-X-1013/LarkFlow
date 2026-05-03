"""A5 部署策略单元测试"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.core import engine
from pipeline.ops.deploy_strategy import (
    DeployOutcome,
    DeployStrategy,
    DockerfileGoStrategy,
    get_strategy,
    register,
)
from pipeline.core.persistence import SqliteSessionStore


class ClassifyFailureTestCase(unittest.TestCase):
    def setUp(self):
        self.strat = DockerfileGoStrategy()

    def test_docker_registry_timeout(self):
        reason = self.strat._classify_failure(
            "docker build", "failed to fetch anonymous token"
        )
        self.assertIn("Docker 外网访问失败", reason)

    def test_alpine_fetch_failure(self):
        reason = self.strat._classify_failure(
            "docker build", "apk add build-base\ntemporary error resolving"
        )
        self.assertIn("Alpine", reason)

    def test_go_mod_download(self):
        reason = self.strat._classify_failure("docker build", "go mod download boom")
        self.assertIn("Go 依赖", reason)

    def test_cgo_missing(self):
        reason = self.strat._classify_failure("docker build", "requires cgo to work")
        self.assertIn("CGO", reason)

    def test_container_health_fallback(self):
        reason = self.strat._classify_failure("container health", "random log")
        self.assertIn("容器已启动但应用很快退出", reason)

    def test_unknown_falls_back_to_stage(self):
        reason = self.strat._classify_failure("some stage", "noise")
        self.assertIn("some stage", reason)


class DockerfileEnsureTestCase(unittest.TestCase):
    def test_ensure_dockerfile_creates_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            strat = DockerfileGoStrategy()
            strat._ensure_dockerfile(tmp)
            dockerfile = Path(tmp) / "Dockerfile"
            self.assertTrue(dockerfile.exists())
            content = dockerfile.read_text(encoding="utf-8")
            template = strat._template_dockerfile_path().read_text(encoding="utf-8")
            self.assertEqual(content, template)

    def test_ensure_dockerfile_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_text("# my custom dockerfile\n", encoding="utf-8")
            DockerfileGoStrategy()._ensure_dockerfile(tmp)
            self.assertEqual(path.read_text(encoding="utf-8"), "# my custom dockerfile\n")

    def test_preflight_reports_missing_proto_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "Makefile").write_text("api:\n\t@echo ok\n", encoding="utf-8")
            (tmp_path / "go.mod").write_text("module demo-app\n\ngo 1.21\n", encoding="utf-8")
            proto_dir = tmp_path / "api" / "user" / "v1"
            proto_dir.mkdir(parents=True)
            (proto_dir / "user.proto").write_text(
                'syntax = "proto3";\noption go_package = "demo-app/api/user/v1;v1";\nimport "google/api/annotations.proto";\nimport "validate/validate.proto";\n',
                encoding="utf-8",
            )

            message = DockerfileGoStrategy()._preflight(tmp)
            self.assertIn("google/api/annotations.proto", message)
            self.assertIn("validate/validate.proto", message)

    def test_preflight_accepts_proto_dependency_in_third_party(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "Makefile").write_text("api:\n\t@echo ok\n", encoding="utf-8")
            (tmp_path / "go.mod").write_text("module demo-app\n\ngo 1.21\n", encoding="utf-8")
            proto_dir = tmp_path / "api" / "user" / "v1"
            proto_dir.mkdir(parents=True)
            (proto_dir / "user.proto").write_text(
                'syntax = "proto3";\noption go_package = "demo-app/api/user/v1;v1";\nimport "google/api/annotations.proto";\nimport "validate/validate.proto";\n',
                encoding="utf-8",
            )
            (tmp_path / "third_party" / "google" / "api").mkdir(parents=True)
            (tmp_path / "third_party" / "validate").mkdir(parents=True)
            (tmp_path / "third_party" / "google" / "api" / "annotations.proto").write_text(
                'syntax = "proto3";\n',
                encoding="utf-8",
            )
            (tmp_path / "third_party" / "validate" / "validate.proto").write_text(
                'syntax = "proto2";\n',
                encoding="utf-8",
            )

            message = DockerfileGoStrategy()._preflight(tmp)
            self.assertEqual(message, "")

    def test_preflight_blocks_when_wire_omits_active_provider_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "Makefile").write_text("api:\n\t@echo ok\n", encoding="utf-8")
            (tmp_path / "go.mod").write_text("module demo-app\n\ngo 1.21\n", encoding="utf-8")
            (tmp_path / "cmd" / "server").mkdir(parents=True)
            (tmp_path / "cmd" / "server" / "wire.go").write_text(
                """package main

import (
\t"demo-app/internal/biz"
\t"demo-app/internal/data"
\t"demo-app/internal/service"
\t"github.com/google/wire"
)

func wireApp() {
\twire.Build(
\t\t// biz.ProviderSet,
\t\t// data.ProviderSet,
\t\t// service.ProviderSet,
\t)
}
""",
                encoding="utf-8",
            )
            (tmp_path / "internal" / "biz").mkdir(parents=True)
            (tmp_path / "internal" / "biz" / "biz.go").write_text(
                """package biz

import "github.com/google/wire"

var ProviderSet = wire.NewSet(NewUserUsecase)
""",
                encoding="utf-8",
            )
            (tmp_path / "internal" / "data").mkdir(parents=True)
            (tmp_path / "internal" / "data" / "data.go").write_text(
                """package data

import "github.com/google/wire"

var ProviderSet = wire.NewSet(NewData, NewUserRepo)
""",
                encoding="utf-8",
            )
            (tmp_path / "internal" / "service").mkdir(parents=True)
            (tmp_path / "internal" / "service" / "service.go").write_text(
                """package service

import "github.com/google/wire"

var ProviderSet = wire.NewSet(NewUserService)
""",
                encoding="utf-8",
            )

            message = DockerfileGoStrategy()._preflight(tmp)
            self.assertIn("Kratos 骨架契约", message)
            self.assertIn("wire.go must enable biz.ProviderSet", message)
            self.assertIn("wire.go must enable data.ProviderSet", message)
            self.assertIn("wire.go must enable service.ProviderSet", message)

    def test_preflight_blocks_wrong_local_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "Makefile").write_text("api:\n\t@echo ok\n", encoding="utf-8")
            (tmp_path / "go.mod").write_text("module demo-app\n\ngo 1.21\n", encoding="utf-8")
            (tmp_path / "cmd" / "server").mkdir(parents=True)
            (tmp_path / "cmd" / "server" / "wire.go").write_text(
                """package main

func wireApp() {}
""",
                encoding="utf-8",
            )
            (tmp_path / "internal" / "service").mkdir(parents=True)
            (tmp_path / "internal" / "service" / "user.go").write_text(
                """package service

import "github.com/demo-app/internal/biz"

var _ = biz.UserUsecase{}
""",
                encoding="utf-8",
            )

            message = DockerfileGoStrategy()._preflight(tmp)
            self.assertIn("Kratos 骨架契约", message)
            self.assertIn("wrong local Go imports", message)
            self.assertIn("github.com/demo-app/internal/biz", message)


class StrategyRegistryTestCase(unittest.TestCase):
    def test_default_is_dockerfile_go(self):
        self.assertIsInstance(get_strategy("docker-go"), DockerfileGoStrategy)

    def test_unknown_name_falls_back(self):
        self.assertIsInstance(get_strategy("not-a-strategy"), DockerfileGoStrategy)
        self.assertIsInstance(get_strategy(None), DockerfileGoStrategy)

    def test_register_custom_strategy(self):
        class EchoStrategy(DeployStrategy):
            name = "echo"

            def deploy(self, target_dir, logger):
                return DeployOutcome(success=True, access_url="echo://")

        register(EchoStrategy())
        got = get_strategy("echo")
        self.assertEqual(got.name, "echo")
        outcome = got.deploy("/tmp", logger=None)
        self.assertEqual(outcome.access_url, "echo://")


class DeployAppDelegationTestCase(unittest.TestCase):
    """engine.deploy_app 应把 session.target_dir / deploy_strategy 正确传给策略"""

    def setUp(self):
        self._db_tmp = tempfile.TemporaryDirectory(prefix="larkflow-a5-")
        self._orig_store = engine.STORE
        engine.STORE = SqliteSessionStore(str(Path(self._db_tmp.name) / "s.db"))
        self._build_client_patch = patch.object(engine, "build_client", return_value=object())
        self._send_lark_text_patch = patch.object(engine, "send_lark_text", return_value=None)
        self._build_client_patch.start()
        self._send_lark_text_patch.start()
        self.demand_id = "DEMAND-A5"

    def tearDown(self):
        self._build_client_patch.stop()
        self._send_lark_text_patch.stop()
        engine.STORE = self._orig_store
        self._db_tmp.cleanup()

    def test_deploy_app_uses_custom_target_dir(self):
        custom_dir = "/custom/target"
        engine.STORE.save(self.demand_id, {
            "provider": "openai", "history": [], "provider_state": {},
            "phase": engine.PHASE_DEPLOYING,
            "target_dir": custom_dir,
        })

        captured = {}

        class SpyStrategy(DeployStrategy):
            name = "spy"

            def deploy(self, target_dir, logger):
                captured["target_dir"] = target_dir
                return DeployOutcome(success=True, access_url="http://spy")

        register(SpyStrategy())
        engine.STORE.save(self.demand_id, {
            **engine.STORE.get(self.demand_id),
            "deploy_strategy": "spy",
        })

        ok = engine.deploy_app(self.demand_id)
        self.assertTrue(ok)
        self.assertEqual(captured["target_dir"], custom_dir)

    def test_deploy_app_returns_false_on_strategy_failure(self):
        engine.STORE.save(self.demand_id, {
            "provider": "openai", "history": [], "provider_state": {},
            "phase": engine.PHASE_DEPLOYING,
            "target_dir": "/tmp",
            "deploy_strategy": "failing",
        })

        class FailingStrategy(DeployStrategy):
            name = "failing"

            def deploy(self, target_dir, logger):
                return DeployOutcome(success=False, reason="simulated failure")

        register(FailingStrategy())
        ok = engine.deploy_app(self.demand_id)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
