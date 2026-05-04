"""tools_runtime.file_editor read 对 skills/ 文件的记录行为单测。

只测 _record_skill_read_if_applicable 的判定逻辑，不跑实际 LLM。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.llm.tools_runtime import ToolContext, _record_skill_read_if_applicable


class RecordSkillReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "skills" / "infra").mkdir(parents=True)
        self.skill_path = self.workspace / "skills" / "infra" / "redis.md"
        self.skill_path.write_text("# Redis", encoding="utf-8")
        (self.workspace / "other").mkdir()
        self.non_skill_path = self.workspace / "other" / "thing.md"
        self.non_skill_path.write_text("x", encoding="utf-8")
        (self.workspace / "skills" / "notes.txt").write_text("nope", encoding="utf-8")
        self.non_md_skill = self.workspace / "skills" / "notes.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def _ctx(self, skills_read):
        return ToolContext(
            demand_id="D1",
            workspace_root=str(self.workspace),
            target_dir=str(self.workspace / "demo-app"),
            skills_read=skills_read,
        )

    def test_records_skill_md_file(self):
        read: set = set()
        _record_skill_read_if_applicable(self.skill_path, self._ctx(read))
        self.assertEqual(read, {"skills/infra/redis.md"})

    def test_skips_non_skills_dir(self):
        read: set = set()
        _record_skill_read_if_applicable(self.non_skill_path, self._ctx(read))
        self.assertEqual(read, set())

    def test_skips_non_md_extension(self):
        read: set = set()
        _record_skill_read_if_applicable(self.non_md_skill, self._ctx(read))
        self.assertEqual(read, set())

    def test_ignored_when_skills_read_is_none(self):
        # None 表示调用方不关心闸门；不应抛异常
        ctx = self._ctx(None)
        _record_skill_read_if_applicable(self.skill_path, ctx)
        self.assertIsNone(ctx.skills_read)

    def test_path_outside_workspace_ignored(self):
        read: set = set()
        outside = Path(tempfile.gettempdir()) / "external.md"
        outside.write_text("x")
        try:
            _record_skill_read_if_applicable(outside, self._ctx(read))
        finally:
            outside.unlink(missing_ok=True)
        self.assertEqual(read, set())


if __name__ == "__main__":
    unittest.main()
