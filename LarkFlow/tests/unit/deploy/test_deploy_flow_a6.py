"""A6 DockerfileGoStrategy.deploy 主流程测试（mock subprocess）"""
import logging
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pipeline import deploy_strategy
from pipeline.deploy_strategy import DockerfileGoStrategy


def _completed(stdout="", stderr="", returncode=0):
    p = MagicMock()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


class DeployFlowTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="deploy-flow-")
        self.target_dir = self._tmp.name
        self.strat = DockerfileGoStrategy()
        self.logger = logging.getLogger("test-deploy")
        self.logger.handlers = [logging.NullHandler()]

    def tearDown(self):
        self._tmp.cleanup()

    def test_full_happy_path(self):
        """build → rm → run → inspect(running) → success"""
        def subprocess_run_side_effect(cmd, *args, **kwargs):
            # docker rm -f 不抛异常即可
            return _completed(stdout="")

        # _run_checked 按顺序: build / run / inspect(status=running)
        run_checked_outputs = [
            _completed(),  # docker build
            _completed(stdout="container-abc\n"),  # docker run
            _completed(stdout="running\n"),  # docker inspect
        ]

        with patch.object(deploy_strategy, "_run_checked", side_effect=run_checked_outputs), \
             patch.object(deploy_strategy.subprocess, "run", side_effect=subprocess_run_side_effect), \
             patch.object(deploy_strategy.time, "sleep", lambda *a: None):
            outcome = self.strat.deploy(self.target_dir, self.logger)

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.access_url, "http://localhost:8080")
        # Dockerfile 已被注入
        self.assertTrue((Path(self.target_dir) / "Dockerfile").exists())

    def test_build_failure_classified(self):
        """docker build 失败 → 分类原因返回"""
        err = subprocess.CalledProcessError(
            1, ["docker", "build", "-t", "demo-app", "."],
            output="", stderr="failed to fetch anonymous token",
        )
        with patch.object(deploy_strategy, "_run_checked", side_effect=err):
            outcome = self.strat.deploy(self.target_dir, self.logger)

        self.assertFalse(outcome.success)
        self.assertIn("Docker 外网访问失败", outcome.reason)

    def test_build_includes_configured_image_mirror_args(self):
        captured = []

        def record_run_checked(cmd, cwd=None):
            captured.append((cmd, cwd))
            if cmd[:2] == ["docker", "build"]:
                return _completed()
            if cmd[:2] == ["docker", "run"]:
                return _completed(stdout="container-abc\n")
            if cmd[:2] == ["docker", "inspect"]:
                return _completed(stdout="running\n")
            raise AssertionError(f"unexpected command: {cmd}")

        with patch.dict(
            os.environ,
            {
                "LARKFLOW_GO_IMAGE": "registry.example.com/library/golang:1.22-alpine",
                "LARKFLOW_ALPINE_MIRROR": "https://mirrors.example.com/alpine",
                "LARKFLOW_GO_PROXY": "https://goproxy.example.com,direct",
            },
            clear=False,
        ), patch.object(deploy_strategy, "_run_checked", side_effect=record_run_checked), \
             patch.object(deploy_strategy.subprocess, "run", return_value=_completed(stdout="")), \
             patch.object(deploy_strategy.time, "sleep", lambda *a: None):
            outcome = self.strat.deploy(self.target_dir, self.logger)

        self.assertTrue(outcome.success)
        build_command = captured[0][0]
        self.assertEqual(build_command[:4], ["docker", "build", "--pull=false", "-t"])
        self.assertIn("--build-arg", build_command)
        self.assertIn(
            "GO_IMAGE=registry.example.com/library/golang:1.22-alpine",
            build_command,
        )
        self.assertIn(
            "ALPINE_MIRROR=https://mirrors.example.com/alpine",
            build_command,
        )
        self.assertIn(
            "GO_PROXY=https://goproxy.example.com,direct",
            build_command,
        )

    def test_container_exits_immediately(self):
        """容器启动后立即退出 → inspect 返回 exited → 失败 + 带日志尾"""
        run_checked_outputs = [
            _completed(),  # build
            _completed(stdout="cid-1\n"),  # run
            _completed(stdout="exited\n"),  # inspect
        ]
        # docker logs 通过 subprocess.run 调用
        logs_output = _completed(stdout="panic: segfault\nat main.go:42\n")

        with patch.object(deploy_strategy, "_run_checked", side_effect=run_checked_outputs), \
             patch.object(deploy_strategy.subprocess, "run", return_value=logs_output), \
             patch.object(deploy_strategy.time, "sleep", lambda *a: None):
            outcome = self.strat.deploy(self.target_dir, self.logger)

        self.assertFalse(outcome.success)
        self.assertIn("容器已启动但应用很快退出", outcome.reason)
        self.assertIn("panic: segfault", outcome.reason)


if __name__ == "__main__":
    unittest.main()
