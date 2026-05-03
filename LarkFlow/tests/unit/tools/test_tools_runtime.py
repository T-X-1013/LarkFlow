import os
import tempfile
import unittest
from pathlib import Path

from pipeline.llm.tools_runtime import ToolContext, execute


class ToolsRuntimeTestCase(unittest.TestCase):
    """覆盖 file_editor 在读写边界、replace 合约和目录校验上的行为。"""

    def setUp(self):
        """
        构造测试用的临时工作区与目标目录。

        @params:
            无

        @return:
            无返回值；在临时目录中准备 workspace_root、target_dir 和测试文件
        """
        # 用临时目录模拟 workspace_root / target_dir / 非法外部路径三种场景。
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace_root = self.root / "workspace"
        self.target_dir = self.root / "demo-app"
        self.workspace_root.mkdir()
        self.target_dir.mkdir()

        rules_dir = self.workspace_root / "rules"
        rules_dir.mkdir()
        (rules_dir / "flow-rule.md").write_text("rules", encoding="utf-8")

        (self.target_dir / "main.go").write_text("package main\n", encoding="utf-8")
        (self.target_dir / "replace.txt").write_text("before value after", encoding="utf-8")
        (self.target_dir / "multi.txt").write_text("dup dup", encoding="utf-8")

        (self.root / "secret.txt").write_text("secret", encoding="utf-8")

        self.ctx = ToolContext(
            demand_id="DEMAND-B1",
            workspace_root=str(self.workspace_root),
            target_dir=str(self.target_dir),
            logger=None,
        )

    def tearDown(self):
        """
        清理临时测试目录。

        @params:
            无

        @return:
            无返回值；释放 setUp 创建的临时目录
        """
        self.temp_dir.cleanup()

    def test_read_allows_workspace_root(self):
        """只读能力应允许访问 workspace_root 内的规则文件。"""
        result = execute("file_editor", {"action": "read", "path": "rules/flow-rule.md"}, self.ctx)
        self.assertEqual(result, "rules")

    def test_read_allows_target_dir(self):
        """只读能力也应覆盖 target_dir，兼容相对 ../demo-app 协议。"""
        result = execute("file_editor", {"action": "read", "path": "../demo-app/main.go"}, self.ctx)
        self.assertEqual(result, "package main\n")

    def test_list_dir_allows_target_dir(self):
        """目录浏览只要位于允许根目录内，就应返回文件列表。"""
        result = execute("file_editor", {"action": "list_dir", "path": "../demo-app"}, self.ctx)
        self.assertIn("main.go", result.splitlines())

    def test_write_allows_target_dir_only(self):
        """写操作只能落在 target_dir 内，不允许改 workspace 规则文件。"""
        result = execute(
            "file_editor",
            {"action": "write", "path": "../demo-app/internal/handler.go", "content": "ok"},
            self.ctx,
        )
        self.assertIn("Successfully wrote", result)
        self.assertEqual((self.target_dir / "internal" / "handler.go").read_text(encoding="utf-8"), "ok")

    def test_write_rejects_workspace_root(self):
        """写 workspace_root 应被拒绝，避免 Agent 误改规则与系统代码。"""
        result = execute(
            "file_editor",
            {"action": "write", "path": "rules/new-rule.md", "content": "nope"},
            self.ctx,
        )
        self.assertIn("Write access denied outside target_dir", result)

    def test_read_rejects_escape_outside_allowed_roots(self):
        """读取越过白名单根目录的文件时应明确拒绝。"""
        result = execute("file_editor", {"action": "read", "path": "../secret.txt"}, self.ctx)
        self.assertIn("Read access denied", result)

    def test_absolute_path_is_rejected(self):
        """绝对路径属于高风险输入，默认直接拒绝。"""
        result = execute("file_editor", {"action": "read", "path": "/etc/passwd"}, self.ctx)
        self.assertIn("Absolute paths are not allowed", result)

    def test_replace_succeeds_when_old_content_matches_once(self):
        """replace 只在 old_content 唯一命中时才允许写回。"""
        result = execute(
            "file_editor",
            {
                "action": "replace",
                "path": "../demo-app/replace.txt",
                "old_content": "value",
                "content": "updated",
            },
            self.ctx,
        )
        self.assertIn("Successfully replaced", result)
        self.assertEqual((self.target_dir / "replace.txt").read_text(encoding="utf-8"), "before updated after")

    def test_replace_rejects_zero_matches(self):
        """replace 找不到 old_content 时应返回可读错误，而不是静默写入。"""
        result = execute(
            "file_editor",
            {
                "action": "replace",
                "path": "../demo-app/replace.txt",
                "old_content": "missing",
                "content": "updated",
            },
            self.ctx,
        )
        self.assertIn("old_content not found", result)

    def test_replace_rejects_multiple_matches(self):
        """replace 命中多处时应拒绝，避免在不确定位置批量替换。"""
        result = execute(
            "file_editor",
            {
                "action": "replace",
                "path": "../demo-app/multi.txt",
                "old_content": "dup",
                "content": "updated",
            },
            self.ctx,
        )
        self.assertIn("old_content matched multiple locations", result)

    def test_replace_rejects_workspace_root(self):
        """replace 本质属于写操作，因此同样不允许落在 workspace_root。"""
        result = execute(
            "file_editor",
            {
                "action": "replace",
                "path": "rules/flow-rule.md",
                "old_content": "rules",
                "content": "updated",
            },
            self.ctx,
        )
        self.assertIn("Write access denied outside target_dir", result)

    def test_replace_rejects_empty_old_content(self):
        """空 old_content 会导致不受控替换，必须在入口处拦截。"""
        result = execute(
            "file_editor",
            {
                "action": "replace",
                "path": "../demo-app/replace.txt",
                "old_content": "",
                "content": "updated",
            },
            self.ctx,
        )
        self.assertIn("replace requires non-empty old_content", result)

    def test_list_dir_rejects_non_directory_path(self):
        """list_dir 只能作用在目录上，对普通文件应给出明确错误。"""
        result = execute("file_editor", {"action": "list_dir", "path": "../demo-app/main.go"}, self.ctx)
        self.assertIn("Not a directory", result)


if __name__ == "__main__":
    unittest.main()
