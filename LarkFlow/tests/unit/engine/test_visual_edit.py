from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from pipeline.ops import visual_edit
from pipeline.core.contracts import ElementRect, VisualEditPreviewRequest, VisualEditTarget


def _build_request(
    *,
    intent: str,
    lark_src: str,
    text: str,
    class_name: str = "",
    tag: str = "p",
) -> VisualEditPreviewRequest:
    """
    构造测试用的视觉编辑预览请求。

    @params:
        intent: 用户修改意图
        lark_src: 前端注入的源码定位串
        text: 当前选中文本
        class_name: 目标元素 className
        tag: 目标标签名

    @return:
        返回一份最小可用的 VisualEditPreviewRequest
    """
    return VisualEditPreviewRequest(
        requirement="【Visual Edit Request】",
        page_url="http://localhost:4173/",
        page_path="/",
        intent=intent,
        target=VisualEditTarget(
            lark_src=lark_src,
            css_selector="body > div:nth-of-type(1)",
            tag=tag,
            id="",
            class_name=class_name,
            text=text,
            rect=ElementRect(left=0, top=0, width=10, height=10),
        ),
    )


@pytest.fixture
def visual_edit_workspace(tmp_path, monkeypatch):
    """
    构造隔离的前端工作区，并把视觉编辑模块重定向到该临时目录。

    @params:
        tmp_path: pytest 提供的临时目录
        monkeypatch: pytest 提供的运行时打桩工具

    @return:
        返回测试用 HomePage.tsx 路径
    """
    workspace = tmp_path / "workspace"
    frontend_src = workspace / "frontend" / "src" / "pages"
    frontend_src.mkdir(parents=True)

    home_page = frontend_src / "HomePage.tsx"
    home_page.write_text(
        """export function HomePage() {
  return (
    <section>
      <h2>原始标题</h2>
      <p className="eyebrow">观测</p>
      <a className="button" href="/pipelines">进入 Pipeline 列表</a>
    </section>
  );
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(visual_edit, "_workspace_root", lambda: workspace)
    monkeypatch.setattr(visual_edit, "_frontend_root", lambda: workspace / "frontend")
    monkeypatch.setattr(visual_edit, "_frontend_src_root", lambda: workspace / "frontend" / "src")
    monkeypatch.setattr(visual_edit, "_SESSIONS", {})

    return home_page


def test_text_preview_and_cancel_restores_file(visual_edit_workspace: Path):
    request = _build_request(
        intent='把文字改成“测观”',
        lark_src="src/pages/HomePage.tsx:4:6",
        text="观测",
    )

    session = visual_edit.create_preview(request)
    assert session.status.value == "preview_ready"
    assert session.changed_files == ["frontend/src/pages/HomePage.tsx"]
    assert session.diff is not None
    assert "-      <p className=\"eyebrow\">观测</p>" in session.diff
    assert "+      <p className=\"eyebrow\">测观</p>" in session.diff
    assert session.diff_summary == ["frontend/src/pages/HomePage.tsx: +1 -1"]
    assert "测观" in visual_edit_workspace.read_text(encoding="utf-8")

    cancelled = visual_edit.cancel_preview(session.id)
    assert cancelled.status.value == "cancelled"
    assert "观测" in visual_edit_workspace.read_text(encoding="utf-8")


def test_text_preview_and_confirm_keeps_file(visual_edit_workspace: Path):
    request = _build_request(
        intent="按钮文案改成立即开始",
        lark_src="src/pages/HomePage.tsx:5:6",
        text="进入 Pipeline 列表",
        class_name="button",
        tag="a",
    )

    session = visual_edit.create_preview(request)
    confirmed = visual_edit.confirm_preview(session.id)
    content = visual_edit_workspace.read_text(encoding="utf-8")

    assert confirmed.status.value == "confirmed"
    assert confirmed.diff_summary == ["frontend/src/pages/HomePage.tsx: +1 -1"]
    assert confirmed.confirmed_files == ["frontend/src/pages/HomePage.tsx"]
    assert confirmed.delivery_summary is not None
    assert "按钮文案改成立即开始" in confirmed.delivery_summary
    assert "frontend/src/pages/HomePage.tsx: +1 -1" in confirmed.delivery_summary
    assert "立即开始" in content
    assert "进入 Pipeline 列表" not in content


def test_color_preview_injects_style_and_cancel_restores_file(visual_edit_workspace: Path):
    request = _build_request(
        intent="把标题改成蓝色",
        lark_src="src/pages/HomePage.tsx:3:6",
        text="原始标题",
        tag="h2",
    )

    session = visual_edit.create_preview(request)
    preview_content = visual_edit_workspace.read_text(encoding="utf-8")
    assert session.status.value == "preview_ready"
    assert 'style={{color: "#3b82f6"}}' in preview_content

    visual_edit.cancel_preview(session.id)
    restored = visual_edit_workspace.read_text(encoding="utf-8")
    assert 'style={{color: "#3b82f6"}}' not in restored


def test_color_preview_uses_background_for_button(visual_edit_workspace: Path):
    request = _build_request(
        intent="把按钮改成红色",
        lark_src="src/pages/HomePage.tsx:5:6",
        text="进入 Pipeline 列表",
        class_name="button",
        tag="a",
    )

    session = visual_edit.create_preview(request)
    preview_content = visual_edit_workspace.read_text(encoding="utf-8")

    assert session.status.value == "preview_ready"
    assert 'style={{backgroundColor: "#ef4444"}}' in preview_content


def test_missing_lark_src_raises_clear_error(visual_edit_workspace: Path):
    request = _build_request(
        intent='把文字改成“测观”',
        lark_src="",
        text="观测",
    )

    with pytest.raises(visual_edit.VisualEditRequestError) as exc:
        visual_edit.create_preview(request)

    assert "data-lark-src" in str(exc.value)


def test_noop_preview_raises_clear_error(visual_edit_workspace: Path):
    request = _build_request(
        intent="把文字改成“观测”",
        lark_src="src/pages/HomePage.tsx:4:6",
        text="观测",
    )

    with pytest.raises(visual_edit.VisualEditRequestError) as exc:
        visual_edit.create_preview(request)

    assert "无需生成预览" in str(exc.value)


def test_delivery_check_hides_unrelated_dirty_file_names(visual_edit_workspace: Path, monkeypatch):
    request = _build_request(
        intent="按钮文案改成立即开始",
        lark_src="src/pages/HomePage.tsx:5:6",
        text="进入 Pipeline 列表",
        class_name="button",
        tag="a",
    )

    session = visual_edit.create_preview(request)
    visual_edit.confirm_preview(session.id)
    monkeypatch.setattr(
        visual_edit,
        "_list_dirty_files",
        lambda: [
            "frontend/src/pages/HomePage.tsx",
            "pipeline/visual_edit.py",
        ],
    )

    check = visual_edit.delivery_check(session.id)

    assert check.confirmed_files == ["frontend/src/pages/HomePage.tsx"]
    assert check.deliverable_files == ["frontend/src/pages/HomePage.tsx"]
    assert check.dirty_file_count == 2
    assert check.unrelated_dirty_count == 1
    assert check.safe_to_commit is False


def test_git_status_paths_are_normalized_to_workspace_relative_paths(tmp_path, monkeypatch):
    git_root = tmp_path / "repo"
    workspace = git_root / "LarkFlow"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(visual_edit, "_workspace_root", lambda: workspace)

    output = "\n".join(
        [
            " M LarkFlow/frontend/src/pages/HomePage.tsx",
            "?? doc/feature.md",
            "?? LarkFlow/pipeline/visual_edit.py",
        ]
    )

    files = visual_edit._parse_git_status_porcelain(output, git_root, workspace)

    assert files == [
        "frontend/src/pages/HomePage.tsx",
        "pipeline/visual_edit.py",
    ]


def test_prepare_commit_returns_plan_without_committing(visual_edit_workspace: Path, monkeypatch):
    request = _build_request(
        intent="按钮文案改成立即开始",
        lark_src="src/pages/HomePage.tsx:5:6",
        text="进入 Pipeline 列表",
        class_name="button",
        tag="a",
    )

    session = visual_edit.create_preview(request)
    visual_edit.confirm_preview(session.id)
    monkeypatch.setattr(
        visual_edit,
        "_list_dirty_files",
        lambda: ["frontend/src/pages/HomePage.tsx"],
    )

    plan = visual_edit.prepare_commit(session.id)

    assert plan.files == ["frontend/src/pages/HomePage.tsx"]
    assert plan.commit_message.startswith("feat(frontend): apply visual edit")
    assert plan.safe_to_commit is True
    assert plan.requires_manual_confirmation is False
    assert plan.warnings == []


def test_commit_visual_edit_commits_only_confirmed_file(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    workspace = repo / "LarkFlow"
    home = workspace / "frontend" / "src" / "pages" / "HomePage.tsx"
    other = workspace / "pipeline" / "visual_edit.py"
    home.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    home.write_text(
        """export function HomePage() {
  return (
    <section>
      <a className="button" href="/pipelines">进入 Pipeline 列表</a>
    </section>
  );
}
""",
        encoding="utf-8",
    )
    other.write_text("# unrelated\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)

    monkeypatch.setattr(visual_edit, "_workspace_root", lambda: workspace)
    monkeypatch.setattr(visual_edit, "_frontend_root", lambda: workspace / "frontend")
    monkeypatch.setattr(visual_edit, "_frontend_src_root", lambda: workspace / "frontend" / "src")
    monkeypatch.setattr(visual_edit, "_git_root", lambda: repo)
    monkeypatch.setattr(visual_edit, "_SESSIONS", {})

    request = _build_request(
        intent="按钮文案改成立即开始",
        lark_src="src/pages/HomePage.tsx:4:6",
        text="进入 Pipeline 列表",
        class_name="button",
        tag="a",
    )
    session = visual_edit.create_preview(request)
    other.write_text("# unrelated dirty\n", encoding="utf-8")
    visual_edit.confirm_preview(session.id)

    with pytest.raises(visual_edit.VisualEditRequestError):
        visual_edit.commit_visual_edit(session.id)

    result = visual_edit.commit_visual_edit(session.id, force=True)
    changed_in_commit = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert result.committed_files == ["frontend/src/pages/HomePage.tsx"]
    assert "LarkFlow/frontend/src/pages/HomePage.tsx" in changed_in_commit
    assert "LarkFlow/pipeline/visual_edit.py" not in changed_in_commit
