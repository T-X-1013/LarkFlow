import os
import tempfile
import unittest
from pathlib import Path

from pipeline.engine import _ensure_target_scaffold, _SCAFFOLD_MARKER


class EnsureTargetScaffoldTestCase(unittest.TestCase):
    """`_ensure_target_scaffold` 是 PR#3 的新钩子，必须在空目录物化、已物化幂等、模板缺失、
    target_dir 非空但缺 marker 这四个场景上行为一致，否则会污染每次需求的起点。
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace_root = self.root / "workspace"
        self.target_dir = self.root / "demo-app"
        self.workspace_root.mkdir()

        # 造一份最小可识别的骨架模板：templates/kratos-skeleton/go.mod + 一个子目录
        self.template_dir = self.workspace_root / "templates" / "kratos-skeleton"
        (self.template_dir / "cmd" / "server").mkdir(parents=True)
        (self.template_dir / "go.mod").write_text("module demo-app\n", encoding="utf-8")
        (self.template_dir / "cmd" / "server" / "main.go").write_text("package main\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_materializes_into_missing_target_dir(self):
        """target_dir 完全不存在时应完整 copytree"""
        self.assertFalse(self.target_dir.exists())
        _ensure_target_scaffold(str(self.workspace_root), str(self.target_dir))
        self.assertTrue((self.target_dir / "go.mod").is_file())
        self.assertTrue((self.target_dir / "cmd" / "server" / "main.go").is_file())

    def test_materializes_into_empty_target_dir(self):
        """target_dir 存在但为空也应正常物化，不应因 copytree 的 dst 存在而报错"""
        self.target_dir.mkdir()
        self.assertEqual(list(self.target_dir.iterdir()), [])
        _ensure_target_scaffold(str(self.workspace_root), str(self.target_dir))
        self.assertTrue((self.target_dir / "go.mod").is_file())

    def test_idempotent_when_marker_present(self):
        """target_dir 已有 go.mod 时必须视为已物化，不覆盖任何现存内容（resume 场景）"""
        self.target_dir.mkdir()
        (self.target_dir / "go.mod").write_text("module existing\n", encoding="utf-8")
        (self.target_dir / "business.go").write_text("package main\n", encoding="utf-8")
        _ensure_target_scaffold(str(self.workspace_root), str(self.target_dir))
        # 保留用户原有 go.mod 内容
        self.assertEqual(
            (self.target_dir / "go.mod").read_text(encoding="utf-8"),
            "module existing\n",
        )
        # 保留用户自己写的 business.go
        self.assertTrue((self.target_dir / "business.go").is_file())
        # 没有把模板文件乱塞进来
        self.assertFalse((self.target_dir / "cmd" / "server" / "main.go").exists())

    def test_refuses_non_empty_without_marker(self):
        """target_dir 非空但缺 go.mod 属于脏状态，应拒绝覆盖以保护未识别的上一次产物"""
        self.target_dir.mkdir()
        (self.target_dir / "stale.go").write_text("// leftover\n", encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            _ensure_target_scaffold(str(self.workspace_root), str(self.target_dir))
        self.assertIn(_SCAFFOLD_MARKER, str(ctx.exception))

    def test_raises_when_template_missing(self):
        """模板目录缺失时不能静默失败，必须给出明确可定位的 FileNotFoundError"""
        # 拆掉模板目录
        import shutil
        shutil.rmtree(self.template_dir)
        with self.assertRaises(FileNotFoundError) as ctx:
            _ensure_target_scaffold(str(self.workspace_root), str(self.target_dir))
        self.assertIn("templates/kratos-skeleton", str(ctx.exception).replace(os.sep, "/"))


if __name__ == "__main__":
    unittest.main()
