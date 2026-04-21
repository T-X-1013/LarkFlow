import os
import tempfile
import unittest
from pathlib import Path

from pipeline.tools_runtime import ToolContext, execute


class ToolsRuntimeTestCase(unittest.TestCase):
    def setUp(self):
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
        self.temp_dir.cleanup()

    def test_read_allows_workspace_root(self):
        result = execute("file_editor", {"action": "read", "path": "rules/flow-rule.md"}, self.ctx)
        self.assertEqual(result, "rules")

    def test_read_allows_target_dir(self):
        result = execute("file_editor", {"action": "read", "path": "../demo-app/main.go"}, self.ctx)
        self.assertEqual(result, "package main\n")

    def test_list_dir_allows_target_dir(self):
        result = execute("file_editor", {"action": "list_dir", "path": "../demo-app"}, self.ctx)
        self.assertIn("main.go", result.splitlines())

    def test_write_allows_target_dir_only(self):
        result = execute(
            "file_editor",
            {"action": "write", "path": "../demo-app/internal/handler.go", "content": "ok"},
            self.ctx,
        )
        self.assertIn("Successfully wrote", result)
        self.assertEqual((self.target_dir / "internal" / "handler.go").read_text(encoding="utf-8"), "ok")

    def test_write_rejects_workspace_root(self):
        result = execute(
            "file_editor",
            {"action": "write", "path": "rules/new-rule.md", "content": "nope"},
            self.ctx,
        )
        self.assertIn("Write access denied outside target_dir", result)

    def test_read_rejects_escape_outside_allowed_roots(self):
        result = execute("file_editor", {"action": "read", "path": "../secret.txt"}, self.ctx)
        self.assertIn("Read access denied", result)

    def test_absolute_path_is_rejected(self):
        result = execute("file_editor", {"action": "read", "path": "/etc/passwd"}, self.ctx)
        self.assertIn("Absolute paths are not allowed", result)

    def test_replace_succeeds_when_old_content_matches_once(self):
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


if __name__ == "__main__":
    unittest.main()
