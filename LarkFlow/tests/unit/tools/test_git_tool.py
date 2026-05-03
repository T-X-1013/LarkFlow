import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.llm.git_tool import (
    GitTool,
    build_branch_name,
    build_commit_message,
    build_pr_title,
    build_semantic_summary,
    slugify_branch_component,
)


class GitToolTestCase(unittest.TestCase):
    """覆盖 GitTool 的分支名、提交信息和本地 git 工作流行为。"""

    def setUp(self):
        """
        初始化一个最小可提交的临时 git 仓库。

        @params:
            无

        @return:
            无返回值；完成 git init、用户配置和首个提交
        """
        # 这里使用临时仓库做真 git 调用测试，避免污染开发者当前工作区。
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name) / "repo"
        self.repo_root.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo_root, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.name", "LarkFlow Bot"],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "bot@example.com"],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        (self.repo_root / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo_root, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        self.tool = GitTool(self.repo_root)

    def tearDown(self):
        """
        清理临时仓库目录。

        @params:
            无

        @return:
            无返回值；释放 setUp 中创建的临时目录
        """
        self.temp_dir.cleanup()

    def test_slugify_branch_component_normalizes_text(self):
        """验证分支 slug 会去空格、去中文并收敛为稳定的英文片段。"""
        slug = slugify_branch_component("  Add Deploy 审批 + Dashboard!  ")
        self.assertEqual(slug, "add-deploy-dashboard")

    def test_build_branch_name_includes_demand_and_summary(self):
        """验证需求 ID 和摘要都会进入分支名，便于后续定位来源。"""
        branch = build_branch_name("DEMAND-123", "Add runtime frontend dashboard", prefix="feature")
        self.assertEqual(branch, "feature/demand-123-add-runtime-frontend-dashboard")

    def test_build_commit_message_and_pr_title_collapse_whitespace(self):
        """验证 commit message 和 PR title 都会做空白折叠。"""
        self.assertEqual(
            build_commit_message("  add   provider  wiring ", demand_id="DEMAND-9"),
            "feat: add provider wiring (DEMAND-9)",
        )
        self.assertEqual(
            build_pr_title("  Add provider wiring ", demand_id="DEMAND-9"),
            "[DEMAND-9] Add provider wiring",
        )

    def test_build_semantic_summary_groups_changed_files(self):
        """验证文件摘要会按 backend / frontend / docs / ci 等类别归并。"""
        summary = build_semantic_summary(
            [
                "pipeline/git_tool.py",
                "frontend/src/App.tsx",
                "tests/unit/tools/test_git_tool.py",
                "docs/install.md",
                ".github/workflows/frontend-ci.yml",
            ]
        )
        self.assertIn("backend(1): pipeline/git_tool.py", summary)
        self.assertIn("frontend(1): frontend/src/App.tsx", summary)
        self.assertIn("tests(1): tests/unit/tools/test_git_tool.py", summary)
        self.assertIn("docs(1): docs/install.md", summary)
        self.assertIn("ci(1): .github/workflows/frontend-ci.yml", summary)

    def test_create_branch_and_commit_all_workflow(self):
        """验证最小本地工作流：建分支、改文件、提交、查看 diff。"""
        branch_name = build_branch_name("DEMAND-42", "Implement git tool workflow")
        create_result = self.tool.create_branch(branch_name)
        self.assertEqual(create_result.returncode, 0)
        self.assertEqual(self.tool.current_branch(), branch_name)

        (self.repo_root / "feature.txt").write_text("hello\n", encoding="utf-8")
        commit_result = self.tool.commit_all(build_commit_message("add feature file", demand_id="DEMAND-42"))
        self.assertEqual(commit_result.returncode, 0)
        self.assertIn("add feature file", commit_result.stdout)

        changed = self.tool.changed_files("HEAD~1..HEAD")
        self.assertEqual(changed, ["feature.txt"])

    def test_commit_all_returns_noop_when_clean(self):
        """工作区干净时不应抛错，而应返回可读的 no-op 结果。"""
        result = self.tool.commit_all(build_commit_message("no changes"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "No staged changes to commit")

    def test_build_gh_pr_command_and_dry_run(self):
        """验证 PR 命令构造和 dry-run 返回值，不要求本机安装 gh。"""
        command = self.tool.build_gh_pr_command(
            title="PR title",
            body="PR body",
            base_branch="main",
            head_branch="feature/demo",
            draft=True,
        )
        self.assertEqual(
            command,
            [
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--title",
                "PR title",
                "--body",
                "PR body",
                "--head",
                "feature/demo",
                "--draft",
            ],
        )

        dry_run = self.tool.create_pull_request(
            title="PR title",
            body="PR body",
            head_branch="feature/demo",
            execute=False,
        )
        self.assertEqual(dry_run.returncode, 0)
        self.assertEqual(dry_run.stdout, "Dry run: gh pr command prepared")


if __name__ == "__main__":
    unittest.main()
