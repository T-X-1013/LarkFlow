"""Step 6 验收：detect_repo_mode + create_pipeline 自动模板选择。

钉死的合约：
1. detect_repo_mode 不动文件系统：目录不存在 / 空目录 / 有 go.mod 三种状态各自正确分类。
2. _auto_select_template：caller 显式传具名模板时不被覆写；只有 "default" 才会按
   repo_mode 切到 "brownfield"。
3. create_pipeline 端到端：mock detect_repo_mode 返回 brownfield 时，注册到
   engine_control 的 ctl.template 必须是 "brownfield"。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.core import engine, engine_api, engine_control


class DetectRepoModeTestCase(unittest.TestCase):
    def test_returns_greenfield_when_target_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "demo-app-not-here")
            self.assertEqual(engine.detect_repo_mode(missing), "greenfield")

    def test_returns_greenfield_when_target_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "demo-app"
            empty.mkdir()
            self.assertEqual(engine.detect_repo_mode(str(empty)), "greenfield")

    def test_returns_brownfield_when_go_mod_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "demo-app"
            target.mkdir()
            (target / "go.mod").write_text("module demo-app\n", encoding="utf-8")
            self.assertEqual(engine.detect_repo_mode(str(target)), "brownfield")


class AutoSelectTemplateTestCase(unittest.TestCase):
    def test_explicit_feature_template_is_kept(self):
        """caller 显式选 feature 时 brownfield 探测不应改写它"""
        with patch.object(engine, "detect_repo_mode", return_value="brownfield"):
            self.assertEqual(engine_api._auto_select_template("feature"), "feature")
            self.assertEqual(engine_api._auto_select_template("bugfix"), "bugfix")
            self.assertEqual(engine_api._auto_select_template("brownfield"), "brownfield")

    def test_default_with_brownfield_switches_to_brownfield(self):
        with patch.object(engine, "detect_repo_mode", return_value="brownfield"):
            self.assertEqual(engine_api._auto_select_template("default"), "brownfield")

    def test_default_with_greenfield_stays_default(self):
        with patch.object(engine, "detect_repo_mode", return_value="greenfield"):
            self.assertEqual(engine_api._auto_select_template("default"), "default")

    def test_detect_failure_falls_back_to_requested(self):
        """文件系统异常不能阻塞创建；降级回原 template"""
        with patch.object(engine, "detect_repo_mode", side_effect=OSError("fs busy")):
            self.assertEqual(engine_api._auto_select_template("default"), "default")


class CreatePipelineEndToEndTestCase(unittest.TestCase):
    """从 engine_api.create_pipeline 这一层验证：模板会真的被写到 ctl 上"""

    def setUp(self):
        # 用 in-memory engine_control 注册器；mock register 拦截写库
        self.captured = {}

        class _FakeCtl:
            demand_id = "DEMAND-STEP6"

        def _fake_register(requirement, template, record_id=None):
            self.captured["requirement"] = requirement
            self.captured["template"] = template
            self.captured["record_id"] = record_id
            return _FakeCtl()

        self._patches = [
            patch.object(engine_control, "register", side_effect=_fake_register),
            patch.object(engine_api, "_session", return_value=None),
            patch.object(
                engine_control,
                "build_state",
                side_effect=lambda ctl, session: ("STATE", ctl.demand_id),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_default_template_with_brownfield_filesystem_picks_brownfield(self):
        with patch.object(engine, "detect_repo_mode", return_value="brownfield"):
            engine_api.create_pipeline("加 nickname 字段", template="default")
        self.assertEqual(self.captured["template"], "brownfield")

    def test_explicit_feature_with_brownfield_filesystem_keeps_feature(self):
        """caller 已经知道自己在做什么；brownfield 探测不能僭越"""
        with patch.object(engine, "detect_repo_mode", return_value="brownfield"):
            engine_api.create_pipeline("加 nickname 字段", template="feature")
        self.assertEqual(self.captured["template"], "feature")

    def test_default_template_with_greenfield_stays_default(self):
        with patch.object(engine, "detect_repo_mode", return_value="greenfield"):
            engine_api.create_pipeline("空仓需求", template="default")
        self.assertEqual(self.captured["template"], "default")


if __name__ == "__main__":
    unittest.main()
