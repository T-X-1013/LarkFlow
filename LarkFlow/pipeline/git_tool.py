"""
LarkFlow Git 工具库

负责：
1. 生成稳定的分支名、提交信息和 PR 标题
2. 在本地仓库执行安全的 branch / add / commit 操作
3. 为后续 gh PR 接线提供可测试的命令构造层
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# 把摘要中的连续空白折叠成单空格，避免分支名和提交信息里出现不可控格式。
_WHITESPACE_RE = re.compile(r"\s+")

# 分支 slug 只保留小写字母、数字和连字符，避免生成 git 不友好的引用名。
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# 分支 slug 过长会影响可读性，也容易和需求前缀拼接后失控，因此统一截断。
_MAX_BRANCH_SLUG_LENGTH = 48


class GitToolError(RuntimeError):
    """Git 工具执行失败时抛出的统一异常。"""


@dataclass(frozen=True)
class GitCommandResult:
    """统一表示一次 git 或 gh 命令的执行结果。"""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """
        判断命令是否执行成功。

        @params:
            无

        @return:
            成功时返回 True，否则返回 False
        """
        return self.returncode == 0


def sanitize_summary_text(text: str) -> str:
    """
    将自然语言摘要收敛为单行、单空格文本。

    @params:
        text: 原始摘要文本，可包含换行和重复空白

    @return:
        返回收敛后的单行文本
    """
    collapsed = _WHITESPACE_RE.sub(" ", (text or "").strip())
    return collapsed.strip()


def slugify_branch_component(text: str, max_length: int = _MAX_BRANCH_SLUG_LENGTH) -> str:
    """
    将任意摘要文本转换为适合放进 git 分支名的 slug。

    @params:
        text: 原始文本
        max_length: slug 最大长度

    @return:
        返回仅包含小写字母、数字和连字符的 slug
    """
    normalized = sanitize_summary_text(text).lower()
    slug = _NON_ALNUM_RE.sub("-", normalized).strip("-")
    if not slug:
        slug = "update"
    return slug[:max_length].rstrip("-")


def build_branch_name(demand_id: str, summary: str, prefix: str = "demand") -> str:
    """
    构造统一格式的需求分支名。

    @params:
        demand_id: 需求 ID
        summary: 需求摘要
        prefix: 分支名前缀，例如 demand、feature

    @return:
        返回 `{prefix}/{demand}-{slug}` 形式的分支名
    """
    demand = slugify_branch_component(demand_id, max_length=24)
    slug = slugify_branch_component(summary)
    return f"{prefix}/{demand}-{slug}"


def build_commit_message(summary: str, demand_id: str | None = None, kind: str = "feat") -> str:
    """
    构造语义化 commit message。

    @params:
        summary: 提交摘要
        demand_id: 可选需求 ID
        kind: Conventional Commit 风格前缀

    @return:
        返回格式化后的 commit message
    """
    cleaned = sanitize_summary_text(summary)
    if not cleaned:
        raise ValueError("summary must not be empty")

    if demand_id:
        return f"{kind}: {cleaned} ({sanitize_summary_text(demand_id)})"
    return f"{kind}: {cleaned}"


def build_pr_title(summary: str, demand_id: str | None = None) -> str:
    """
    构造 PR 标题。

    @params:
        summary: PR 摘要
        demand_id: 可选需求 ID

    @return:
        返回格式化后的 PR 标题
    """
    cleaned = sanitize_summary_text(summary)
    if not cleaned:
        raise ValueError("summary must not be empty")

    if demand_id:
        return f"[{sanitize_summary_text(demand_id)}] {cleaned}"
    return cleaned


def build_semantic_summary(changed_files: Iterable[str]) -> str:
    """
    将变更文件列表压缩成适合 PR / 卡片展示的语义摘要。

    @params:
        changed_files: 变更文件路径列表

    @return:
        返回按 backend / frontend / tests / docs / ci 等类别归纳后的摘要
    """
    categories: dict[str, list[str]] = {
        "frontend": [],
        "backend": [],
        "tests": [],
        "docs": [],
        "ci": [],
        "other": [],
    }

    for raw_path in changed_files:
        path = str(raw_path).strip()
        if not path:
            continue
        if "/frontend/" in path or path.startswith("frontend/"):
            categories["frontend"].append(path)
        elif "/tests/" in path or path.startswith("tests/"):
            categories["tests"].append(path)
        elif "/docs/" in path or path.startswith("docs/") or path.endswith(".md"):
            categories["docs"].append(path)
        elif ".github/workflows/" in path or path.startswith(".github/"):
            categories["ci"].append(path)
        elif "/pipeline/" in path or path.startswith("pipeline/"):
            categories["backend"].append(path)
        else:
            categories["other"].append(path)

    parts: list[str] = []
    for label in ("backend", "frontend", "tests", "docs", "ci", "other"):
        files = categories[label]
        if not files:
            continue
        preview = ", ".join(files[:3])
        if len(files) > 3:
            preview = f"{preview}, +{len(files) - 3} more"
        parts.append(f"{label}({len(files)}): {preview}")

    return "; ".join(parts) if parts else "no file changes detected"


@dataclass
class GitTool:
    repo_root: Path | str

    def __post_init__(self) -> None:
        """
        把仓库根目录统一解析成绝对路径。

        @params:
            无

        @return:
            无返回值；直接原地更新 `repo_root`
        """
        self.repo_root = Path(self.repo_root).resolve()

    def _run(self, args: Sequence[str], check: bool = True) -> GitCommandResult:
        """
        在目标仓库中执行一条 git 命令。

        @params:
            args: 传给 git 的参数列表，不含前缀 `git`
            check: 为 True 时，失败会抛出 GitToolError

        @return:
            返回统一封装后的 GitCommandResult
        """
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.repo_root),
            text=True,
            capture_output=True,
        )
        result = GitCommandResult(
            args=tuple(["git", *args]),
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        if check and not result.ok:
            message = result.stderr or result.stdout or "git command failed"
            raise GitToolError(message)
        return result

    def ensure_repo(self) -> Path:
        """
        校验当前 repo_root 是否位于有效 git 仓库内。

        @params:
            无

        @return:
            返回 git 识别到的仓库根目录绝对路径
        """
        result = self._run(["rev-parse", "--show-toplevel"])
        return Path(result.stdout).resolve()

    def current_branch(self) -> str:
        """
        读取当前检出的分支名。

        @params:
            无

        @return:
            返回当前分支名
        """
        result = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
        return result.stdout

    def create_branch(self, branch_name: str, start_point: str | None = None) -> GitCommandResult:
        """
        从当前仓库创建并切换到新分支。

        @params:
            branch_name: 新分支名
            start_point: 可选起点引用；为空时从当前 HEAD 切出

        @return:
            返回执行 checkout -b 的命令结果
        """
        self.ensure_repo()
        args = ["checkout", "-b", branch_name]
        if start_point:
            args.append(start_point)
        return self._run(args)

    def changed_files(self, refspec: str = "HEAD") -> list[str]:
        """
        读取指定 refspec 下的变更文件列表。

        @params:
            refspec: 传给 `git diff --name-only` 的范围表达式

        @return:
            返回去空行后的变更文件路径列表
        """
        result = self._run(["diff", "--name-only", refspec], check=False)
        if not result.ok and not result.stdout:
            message = result.stderr or result.stdout or f"failed to diff against {refspec}"
            raise GitToolError(message)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def commit_all(self, message: str) -> GitCommandResult:
        """
        暂存仓库内所有改动并执行提交。

        @params:
            message: 提交信息

        @return:
            若存在变更则返回实际 commit 结果；否则返回一个 no-op 结果
        """
        self.ensure_repo()
        self._run(["add", "-A"])
        staged = self._run(["diff", "--cached", "--name-only"], check=False)
        if not staged.stdout.strip():
            return GitCommandResult(
                args=("git", "commit", "-m", message),
                returncode=0,
                stdout="No staged changes to commit",
                stderr="",
            )
        return self._run(["commit", "-m", message])

    def commit_files(self, files: Iterable[str], message: str) -> GitCommandResult:
        """
        只暂存指定文件并执行提交，避免把工作区里的其他改动带进去。

        @params:
            files: 需要提交的仓库相对路径列表
            message: 提交信息

        @return:
            若存在 staged 变更则返回实际 commit 结果；否则返回 no-op 结果
        """
        self.ensure_repo()
        file_list = [str(path).strip() for path in files if str(path).strip()]
        if not file_list:
            raise GitToolError("no files provided for commit")
        self._run(["add", "--", *file_list])
        staged = self._run(["diff", "--cached", "--name-only", "--", *file_list], check=False)
        if not staged.stdout.strip():
            return GitCommandResult(
                args=("git", "commit", "-m", message),
                returncode=0,
                stdout="No staged changes to commit",
                stderr="",
            )
        return self._run(["commit", "-m", message])

    def build_gh_pr_command(
        self,
        *,
        title: str,
        body: str,
        base_branch: str = "main",
        head_branch: str | None = None,
        draft: bool = True,
    ) -> list[str]:
        """
        构造 `gh pr create` 命令参数。

        @params:
            title: PR 标题
            body: PR 描述
            base_branch: 目标基线分支
            head_branch: 可选来源分支；为空时由 gh 自行推断
            draft: 是否创建 draft PR

        @return:
            返回可直接传给 subprocess 的命令参数列表
        """
        command = ["gh", "pr", "create", "--base", base_branch, "--title", title, "--body", body]
        if head_branch:
            command.extend(["--head", head_branch])
        if draft:
            command.append("--draft")
        return command

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        base_branch: str = "main",
        head_branch: str | None = None,
        draft: bool = True,
        execute: bool = False,
    ) -> GitCommandResult:
        """
        创建 GitHub Pull Request，或返回 dry-run 命令。

        @params:
            title: PR 标题
            body: PR 描述
            base_branch: 目标基线分支
            head_branch: 可选来源分支
            draft: 是否创建 draft PR
            execute: 为 False 时不真正执行 gh，只返回 dry-run 结果

        @return:
            execute=False 时返回 dry-run 结果；否则返回 gh 命令执行结果
        """
        command = self.build_gh_pr_command(
            title=title,
            body=body,
            base_branch=base_branch,
            head_branch=head_branch,
            draft=draft,
        )
        if not execute:
            return GitCommandResult(
                args=tuple(command),
                returncode=0,
                stdout="Dry run: gh pr command prepared",
                stderr="",
            )

        if shutil.which("gh") is None:
            raise GitToolError("GitHub CLI 'gh' is not installed")

        completed = subprocess.run(
            command,
            cwd=str(self.repo_root),
            text=True,
            capture_output=True,
        )
        result = GitCommandResult(
            args=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        if not result.ok:
            message = result.stderr or result.stdout or "gh pr create failed"
            raise GitToolError(message)
        return result
