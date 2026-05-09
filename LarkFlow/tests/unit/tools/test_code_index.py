"""Step 2 新增的轻量代码索引工具测试：grep_symbol / list_dir_summary。

inventory 节点要靠这两个工具在不读全文件的前提下建立"项目长什么样"的认知，
所以这里重点验证：
1. 能在 workspace_root / target_dir 内定位匹配；
2. 自动跳过 vendor / .git / node_modules 这类噪音目录；
3. max_results / depth / max_entries 这些上下文保护参数真的生效；
4. 越界、非法 path、坏正则等失败路径返回可读错误文本。
"""
import tempfile
import unittest
from pathlib import Path

from pipeline.llm.tools_runtime import ToolContext, execute


class CodeIndexToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace_root = self.root / "workspace"
        self.target_dir = self.root / "demo-app"
        self.workspace_root.mkdir()
        self.target_dir.mkdir()

        # 模拟一个最小 Kratos 风格存量代码
        (self.target_dir / "internal" / "biz").mkdir(parents=True)
        (self.target_dir / "internal" / "biz" / "user.go").write_text(
            "package biz\n\ntype UserUsecase struct {}\n\nfunc (u *UserUsecase) Register() {}\n",
            encoding="utf-8",
        )
        (self.target_dir / "internal" / "biz" / "order.go").write_text(
            "package biz\n\ntype OrderUsecase struct {}\n",
            encoding="utf-8",
        )
        (self.target_dir / "go.mod").write_text("module demo-app\n", encoding="utf-8")

        # 噪音目录：必须被跳过
        (self.target_dir / "vendor" / "github.com" / "fake").mkdir(parents=True)
        (self.target_dir / "vendor" / "github.com" / "fake" / "lib.go").write_text(
            "type UserUsecase struct{}\n", encoding="utf-8",
        )
        (self.target_dir / ".git").mkdir()
        (self.target_dir / ".git" / "HEAD").write_text("UserUsecase\n", encoding="utf-8")

        self.ctx = ToolContext(
            demand_id="DEMAND-STEP2",
            workspace_root=str(self.workspace_root),
            target_dir=str(self.target_dir),
            logger=None,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    # ---------- grep_symbol ----------

    def test_grep_symbol_finds_matches_and_skips_noise_dirs(self):
        """命中 internal/biz 下的 UserUsecase，但 vendor/.git 里的同名匹配必须被跳过"""
        result = execute(
            "grep_symbol",
            {"pattern": r"\bUserUsecase\b"},
            self.ctx,
        )
        normalized = result.replace("\\", "/")
        self.assertIn("internal/biz/user.go", normalized)
        self.assertNotIn("vendor", result)
        self.assertNotIn(".git", result)
        # user.go 里 type UserUsecase + func receiver 各一次，共 2 处命中
        self.assertIn("MATCHES: 2", result)

    def test_grep_symbol_respects_file_glob(self):
        """file_glob='*.proto' 不应在纯 .go 仓里命中任何东西"""
        result = execute(
            "grep_symbol",
            {"pattern": "Usecase", "file_glob": "*.proto"},
            self.ctx,
        )
        self.assertIn("MATCHES: 0", result)
        self.assertIn("<no matches>", result)

    def test_grep_symbol_caps_max_results(self):
        """max_results=1 时即便匹配多处也只返回 1 行"""
        # 再制造一个 Usecase 命中
        (self.target_dir / "internal" / "biz" / "extra.go").write_text(
            "type FooUsecase struct{}\n", encoding="utf-8",
        )
        result = execute(
            "grep_symbol",
            {"pattern": "Usecase", "max_results": 1},
            self.ctx,
        )
        self.assertIn("MATCHES: 1 (max=1)", result)

    def test_grep_symbol_rejects_invalid_regex(self):
        """坏正则不应让工具崩，要返回 'Code index failed:' 前缀错误"""
        result = execute(
            "grep_symbol",
            {"pattern": "[unclosed"},
            self.ctx,
        )
        self.assertTrue(result.startswith("Code index failed:"), result)

    def test_grep_symbol_rejects_absolute_path(self):
        """绝对路径必须被边界拦截"""
        result = execute(
            "grep_symbol",
            {"pattern": "x", "path": "/etc"},
            self.ctx,
        )
        self.assertTrue(result.startswith("Code index failed:"), result)

    def test_grep_symbol_rejects_path_outside_allowed_roots(self):
        """走 ../../.. 跳出 workspace 必须 PermissionError"""
        outside = self.root / "secret"
        outside.mkdir()
        (outside / "leak.go").write_text("UserUsecase", encoding="utf-8")
        # 通过 workspace_root + ".." 拼出越界路径
        result = execute(
            "grep_symbol",
            {"pattern": "Usecase", "path": "../secret"},
            self.ctx,
        )
        self.assertTrue(result.startswith("Code index failed:"), result)

    # ---------- list_dir_summary ----------

    def test_list_dir_summary_default_root_is_target_dir(self):
        """不传 path 默认从 target_dir 起，列出 go.mod 与 internal/"""
        result = execute("list_dir_summary", {}, self.ctx)
        self.assertIn("go.mod", result)
        self.assertIn("internal/", result)
        # 噪音目录不应出现
        self.assertNotIn("vendor", result)
        self.assertNotIn(".git", result)

    def test_list_dir_summary_depth_caps_recursion(self):
        """depth=1 时只看到顶层，不应深入 internal/biz/user.go"""
        result = execute("list_dir_summary", {"depth": 1}, self.ctx)
        self.assertIn("internal/", result)
        self.assertNotIn("user.go", result)

    def test_list_dir_summary_max_entries_truncates(self):
        """max_entries=2 应触发 (truncated) 并把条目压回 2 条"""
        result = execute("list_dir_summary", {"max_entries": 2}, self.ctx)
        self.assertIn("(truncated)", result)
        # 解析 ENTRIES 行，确认 <= 2
        for line in result.splitlines():
            if line.startswith("ENTRIES:"):
                # 形如 "ENTRIES: 2 (truncated)"
                parts = line.split()
                self.assertEqual(parts[1], "2")
                break
        else:
            self.fail("missing ENTRIES line in output")

    def test_list_dir_summary_reports_file_size_not_content(self):
        """文件应附带字节大小标记，但绝不能把文件内容塞进结果"""
        result = execute("list_dir_summary", {"depth": 1}, self.ctx)
        self.assertRegex(result, r"go\.mod\s+\(\d+B\)")
        self.assertNotIn("module demo-app", result)


if __name__ == "__main__":
    unittest.main()
