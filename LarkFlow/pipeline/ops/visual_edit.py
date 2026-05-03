"""
前端视觉编辑预览服务。

负责：
1. 根据圈选结果和用户意图在本地生成一次可回滚的前端预览
2. 管理预览、确认、取消、交付检查和提交前计划这条状态流转
3. 限制改动范围只落在 frontend/src，避免预览过程误改其他仓库内容
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path

from pipeline.core.contracts import (
    VisualEditCommitPlan,
    VisualEditCommitResult,
    VisualEditDeliveryCheck,
    VisualEditPreviewRequest,
    VisualEditSession,
    VisualEditSessionStatus,
    VisualEditTarget,
)
from pipeline.llm.git_tool import GitTool, GitToolError


class VisualEditNotFoundError(KeyError):
    """Raised when a visual edit session does not exist."""


class VisualEditRequestError(ValueError):
    """Raised when a visual edit request cannot be applied safely."""


@dataclass
class _StoredVisualEditSession:
    session: VisualEditSession
    snapshots: dict[str, str] = field(default_factory=dict)


_SESSIONS: dict[str, _StoredVisualEditSession] = {}
_LOCK = threading.Lock()
_TEXT_PATTERNS = (
    re.compile(r'改成[“"](.+?)[”"]'),
    re.compile(r'改为[“"](.+?)[”"]'),
    re.compile(r'换成[“"](.+?)[”"]'),
    re.compile(r'替换成[“"](.+?)[”"]'),
    re.compile(r'显示为[“"](.+?)[”"]'),
    re.compile(r'标题叫[“"](.+?)[”"]'),
    re.compile(r'按钮文案改成[“"](.+?)[”"]'),
    re.compile(r'文案改成[“"](.+?)[”"]'),
    re.compile(r'文字改成[“"](.+?)[”"]'),
    re.compile(r'改成\s*([^。]+)$'),
    re.compile(r'改为\s*([^。]+)$'),
    re.compile(r'换成\s*([^。]+)$'),
    re.compile(r'替换成\s*([^。]+)$'),
    re.compile(r'显示为\s*([^。]+)$'),
    re.compile(r'标题叫\s*([^。]+)$'),
    re.compile(r'按钮文案改成\s*([^。]+)$'),
    re.compile(r'改成\s+(.+)$'),
)
_COLOR_ALIASES = {
    "蓝色": "#3b82f6",
    "浅蓝色": "#60a5fa",
    "深蓝色": "#1d4ed8",
    "红色": "#ef4444",
    "橙色": "#f97316",
    "绿色": "#22c55e",
    "黄色": "#eab308",
    "紫色": "#8b5cf6",
    "黑色": "#111827",
    "白色": "#ffffff",
    "灰色": "#6b7280",
}
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")


def _now() -> int:
    """
    返回当前 Unix 时间戳。

    @params:
        无

    @return:
        返回秒级时间戳
    """
    return int(time.time())


def _workspace_root() -> Path:
    """
    返回 LarkFlow 工作区根目录。

    @params:
        无

    @return:
        返回当前模块所属仓库的工作区根路径
    """
    return Path(__file__).resolve().parents[2]


def _frontend_root() -> Path:
    """
    返回前端工程根目录。

    @params:
        无

    @return:
        返回 frontend 目录绝对路径
    """
    return _workspace_root() / "frontend"


def _frontend_src_root() -> Path:
    """
    返回允许视觉编辑落盘的源码根目录。

    @params:
        无

    @return:
        返回 frontend/src 目录绝对路径
    """
    return _frontend_root() / "src"


def _git_root() -> Path:
    """
    读取当前工作区所在的 git 仓库根目录。

    @params:
        无

    @return:
        返回 git 仓库根目录绝对路径
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=_workspace_root(),
        check=True,
        text=True,
        capture_output=True,
    )
    return Path(result.stdout.strip()).resolve()


def _resolve_target_file(lark_src: str | None) -> tuple[Path, int | None]:
    """
    将前端注入的 data-lark-src 解析成目标源码文件和近似行号。

    @params:
        lark_src: Vite dev 模式注入的源码定位串，格式为 `src/...:line[:column]`

    @return:
        返回目标文件绝对路径和可选行号
    """
    if not lark_src:
        raise VisualEditRequestError("当前预览 MVP 依赖 data-lark-src；请在 Vite dev 模式下重试。")

    parts = lark_src.split(":")
    if not parts:
        raise VisualEditRequestError("无效的 lark_src。")

    rel_path = parts[0]
    if not rel_path.startswith("src/"):
        raise VisualEditRequestError(f"不支持的源码路径: {rel_path}")

    target_file = (_frontend_root() / rel_path).resolve()
    src_root = _frontend_src_root().resolve()
    try:
        # 预览只允许修改 frontend/src，避免圈选能力误改脚手架、配置或后端代码。
        target_file.relative_to(src_root)
    except ValueError as exc:
        raise VisualEditRequestError(f"目标文件不在 frontend/src 下: {target_file}") from exc

    line_no = None
    if len(parts) >= 2 and parts[1].isdigit():
        line_no = int(parts[1])
    return target_file, line_no


def _extract_desired_text(intent: str) -> str:
    """
    从自然语言意图中提取目标文案。

    @params:
        intent: 用户在圈选面板里输入的修改意图

    @return:
        返回解析出的目标文本
    """
    normalized = (intent or "").strip()
    for pattern in _TEXT_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        value = match.group(1).strip().strip("。").strip('“”"')
        if value:
            return value
    raise VisualEditRequestError("当前预览 MVP 只支持明确的文本替换，例如：把文字改成“测观”。")


def _extract_desired_color(intent: str) -> str:
    """
    从自然语言意图中提取目标颜色。

    @params:
        intent: 用户在圈选面板里输入的颜色修改意图

    @return:
        返回十六进制颜色值
    """
    normalized = (intent or "").strip()
    direct = _HEX_COLOR_RE.search(normalized)
    if direct:
        return direct.group(0)
    for name, value in _COLOR_ALIASES.items():
        if name in normalized:
            return value
    raise VisualEditRequestError("当前预览未识别到颜色值，请使用明确颜色，例如：蓝色、红色或 #3b82f6。")


def _looks_like_color_change(intent: str) -> bool:
    """
    粗略判断当前意图是否属于颜色修改。

    @params:
        intent: 用户输入的修改意图

    @return:
        命中颜色关键词或颜色值时返回 True，否则返回 False
    """
    normalized = (intent or "").strip()
    has_named_color = any(key in normalized for key in _COLOR_ALIASES)
    has_color_verb = any(verb in normalized for verb in ("改成", "改为", "换成", "变成"))
    return ("颜色" in normalized) or (has_named_color and has_color_verb) or (_HEX_COLOR_RE.search(normalized) is not None)


def _replace_text_near_line(source: str, current_text: str, new_text: str, line_no: int | None) -> str:
    """
    优先在目标行附近执行文本替换，降低同文案多处出现时的误改概率。

    @params:
        source: 原始源码文本
        current_text: 当前圈选元素可见文本
        new_text: 目标替换文本
        line_no: 由 data-lark-src 提供的近似源码行号

    @return:
        返回替换后的源码文本
    """
    if not current_text:
        raise VisualEditRequestError("当前预览 MVP 需要选中元素包含可见文本。")
    if current_text == new_text:
        return source

    lines = source.splitlines(keepends=True)
    candidate_indexes: list[int] = []
    if line_no is not None and 1 <= line_no <= len(lines):
        start = max(0, line_no - 3)
        end = min(len(lines), line_no + 2)
        candidate_indexes.extend(range(start, end))

    # 先尝试只在目标行附近改动，避免全文件范围内误替换到同名文案。
    for idx in candidate_indexes:
        if current_text not in lines[idx]:
            continue
        lines[idx] = lines[idx].replace(current_text, new_text, 1)
        return "".join(lines)

    occurrences = source.count(current_text)
    if occurrences == 1:
        return source.replace(current_text, new_text, 1)
    if occurrences == 0:
        raise VisualEditRequestError("没有在目标文件中找到选中文本，无法生成预览。")
    raise VisualEditRequestError("选中文本在目标文件中出现多次，当前预览 MVP 无法安全定位。")


def _find_opening_tag_range(source: str, line_no: int | None) -> tuple[int, int]:
    """
    根据近似行号定位 JSX 起始标签的源码范围。

    @params:
        source: 原始源码文本
        line_no: 圈选定位给出的近似行号

    @return:
        返回标签起止位置的字符偏移
    """
    lines = source.splitlines(keepends=True)
    if line_no is None or not (1 <= line_no <= len(lines)):
        raise VisualEditRequestError("当前颜色预览需要有效的源码行号定位。")

    start = line_no - 1
    while start >= 0 and "<" not in lines[start]:
        start -= 1
    if start < 0:
        raise VisualEditRequestError("没有定位到目标 JSX 标签起始位置。")

    end = start
    while end < len(lines) and ">" not in lines[end]:
        end += 1
    if end >= len(lines):
        raise VisualEditRequestError("没有定位到目标 JSX 标签结束位置。")

    abs_start = sum(len(line) for line in lines[:start])
    abs_end = sum(len(line) for line in lines[: end + 1])
    return abs_start, abs_end


def _choose_color_property(target: VisualEditTarget, intent: str) -> str:
    """
    根据目标元素和意图决定写入 `color` 还是 `backgroundColor`。

    @params:
        target: 圈选得到的目标元素信息
        intent: 用户输入的颜色修改意图

    @return:
        返回 JSX style 中要写入的属性名
    """
    class_name = (target.class_name or "").lower()
    normalized = (intent or "").strip()
    if "背景" in normalized or "按钮" in normalized or "button" in class_name:
        return "backgroundColor"
    return "color"


def _inject_or_replace_style(opening_tag: str, property_name: str, color_value: str) -> str:
    """
    在 JSX 起始标签中注入或更新 style 属性。

    @params:
        opening_tag: 目标 JSX 起始标签源码
        property_name: 要写入的样式属性名
        color_value: 目标颜色值

    @return:
        返回更新后的起始标签源码
    """
    style_match = re.search(r"style=\{\{(.*?)\}\}", opening_tag, re.DOTALL)
    if style_match:
        body = style_match.group(1)
        prop_re = re.compile(rf"{property_name}\s*:\s*[\"']?[^,}}]+[\"']?")
        replacement = f'{property_name}: "{color_value}"'
        if prop_re.search(body):
            new_body = prop_re.sub(replacement, body, count=1)
        else:
            trimmed = body.strip()
            if trimmed and not trimmed.endswith(","):
                trimmed = f"{trimmed}, "
            new_body = f"{trimmed}{replacement}"
        return opening_tag[: style_match.start()] + f"style={{{{{new_body}}}}}" + opening_tag[style_match.end():]

    close_idx = opening_tag.rfind(">")
    if close_idx < 0:
        raise VisualEditRequestError("目标 JSX 标签缺少结束符号，无法注入 style。")
    style_attr = f' style={{{{{property_name}: "{color_value}"}}}}'
    return opening_tag[:close_idx] + style_attr + opening_tag[close_idx:]


def _apply_color_change(source: str, target: VisualEditTarget, intent: str, line_no: int | None) -> str:
    """
    把颜色修改意图落到目标 JSX 标签上。

    @params:
        source: 原始源码文本
        target: 圈选得到的目标元素信息
        intent: 用户输入的颜色修改意图
        line_no: 圈选定位给出的近似行号

    @return:
        返回更新后的源码文本
    """
    color_value = _extract_desired_color(intent)
    property_name = _choose_color_property(target, intent)
    start, end = _find_opening_tag_range(source, line_no)
    opening_tag = source[start:end]
    updated_tag = _inject_or_replace_style(opening_tag, property_name, color_value)
    return source[:start] + updated_tag + source[end:]


def _build_unified_diff(relative_path: str, before: str, after: str) -> str:
    """
    为单文件预览构造 unified diff 文本。

    @params:
        relative_path: 工作区相对路径
        before: 修改前源码
        after: 修改后源码

    @return:
        返回适合前端直接展示的 diff 文本
    """
    return "".join(
        unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    )


def _build_diff_summary(relative_path: str, before: str, after: str) -> list[str]:
    """
    生成供面板展示的单行 diff 摘要。

    @params:
        relative_path: 工作区相对路径
        before: 修改前源码
        after: 修改后源码

    @return:
        返回 `文件: +新增 -删除` 形式的摘要列表
    """
    removed = 0
    added = 0
    for line in unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
        lineterm="",
    ):
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-"):
            removed += 1
        elif line.startswith("+"):
            added += 1
    return [f"{relative_path}: +{added} -{removed}"]


def _build_delivery_summary(session: VisualEditSession) -> str:
    """
    生成确认后可回显给用户的交付摘要。

    @params:
        session: 已生成预览的视觉编辑会话

    @return:
        返回多行文本摘要
    """
    files = "\n".join(f"- {path}" for path in session.changed_files) or "- 无"
    diff_items = "\n".join(f"- {item}" for item in session.diff_summary) or "- 无"
    return "\n".join(
        [
            "## Visual Edit Delivery Summary",
            "",
            f"- Session: {session.id}",
            f"- Intent: {session.intent}",
            f"- Page: {session.page_path}",
            "",
            "## Changed Files",
            files,
            "",
            "## Diff Summary",
            diff_items,
        ]
    )


def _build_commit_message(session: VisualEditSession) -> str:
    """
    为视觉编辑提交生成简短 commit message。

    @params:
        session: 已确认的视觉编辑会话

    @return:
        返回符合 conventional commit 风格的提交信息
    """
    intent = re.sub(r"\s+", " ", session.intent).strip()
    if len(intent) > 48:
        intent = f"{intent[:45]}..."
    return f"feat(frontend): apply visual edit {intent}"


def _restore_locked(stored: _StoredVisualEditSession) -> None:
    """
    在持锁状态下把预览改动回滚到原始快照。

    @params:
        stored: 持有源码快照的视觉编辑会话

    @return:
        无返回值
    """
    for raw_path, content in stored.snapshots.items():
        Path(raw_path).write_text(content, encoding="utf-8")


def _cancel_active_preview_sessions_locked(exclude_session_id: str | None = None) -> None:
    """
    取消其他仍在活跃中的预览会话，保证同一时刻只有一份落盘预览生效。

    @params:
        exclude_session_id: 需要保留的会话 ID；为空时取消全部活跃预览

    @return:
        无返回值
    """
    for session_id, stored in _SESSIONS.items():
        if session_id == exclude_session_id:
            continue
        if stored.session.status not in (
            VisualEditSessionStatus.EDITING,
            VisualEditSessionStatus.PREVIEW_READY,
            VisualEditSessionStatus.CONFIRMING,
        ):
            continue
        _restore_locked(stored)
        stored.snapshots.clear()
        stored.session.status = VisualEditSessionStatus.CANCELLED
        stored.session.error = "Superseded by a newer preview session."
        stored.session.updated_at = _now()


def create_preview(request: VisualEditPreviewRequest) -> VisualEditSession:
    """
    创建一次视觉编辑预览，并把修改临时落盘到目标前端文件。

    @params:
        request: 预览请求，包含页面信息、圈选目标和用户意图

    @return:
        返回进入 preview_ready 或 failed 状态的视觉编辑会话
    """
    session_id = f"VE-{uuid.uuid4().hex[:8]}"
    now = _now()
    session = VisualEditSession(
        id=session_id,
        requirement=request.requirement,
        page_url=request.page_url,
        page_path=request.page_path,
        intent=request.intent,
        target=request.target,
        status=VisualEditSessionStatus.EDITING,
        preview_url=request.page_url,
        created_at=now,
        updated_at=now,
    )

    with _LOCK:
        # 当前实现只允许一个活跃预览直接落盘，新的预览会顶掉旧会话，避免多个临时改动相互覆盖。
        _cancel_active_preview_sessions_locked()
        stored = _StoredVisualEditSession(session=session)
        _SESSIONS[session_id] = stored

        try:
            target_file, line_no = _resolve_target_file(request.target.lark_src)
            current_source = target_file.read_text(encoding="utf-8")
            if _looks_like_color_change(request.intent):
                updated_source = _apply_color_change(
                    current_source,
                    request.target,
                    request.intent,
                    line_no,
                )
            else:
                desired_text = _extract_desired_text(request.intent)
                updated_source = _replace_text_near_line(
                    current_source,
                    request.target.text,
                    desired_text,
                    line_no,
                )
            if updated_source == current_source:
                raise VisualEditRequestError("目标内容已经符合修改意图，无需生成预览。")
            relative_path = str(target_file.resolve().relative_to(_workspace_root().resolve()))
            stored.snapshots[str(target_file)] = current_source
            target_file.write_text(updated_source, encoding="utf-8")
            stored.session.changed_files = [relative_path]
            stored.session.diff = _build_unified_diff(relative_path, current_source, updated_source)
            stored.session.diff_summary = _build_diff_summary(relative_path, current_source, updated_source)
            stored.session.status = VisualEditSessionStatus.PREVIEW_READY
            stored.session.updated_at = _now()
            return stored.session.model_copy(deep=True)
        except Exception as exc:  # noqa: BLE001
            stored.session.status = VisualEditSessionStatus.FAILED
            stored.session.error = str(exc)
            stored.session.updated_at = _now()
            raise


def get_session(session_id: str) -> VisualEditSession:
    """
    读取指定视觉编辑会话的最新快照。

    @params:
        session_id: 视觉编辑会话 ID

    @return:
        返回会话的深拷贝快照
    """
    with _LOCK:
        stored = _SESSIONS.get(session_id)
        if stored is None:
            raise VisualEditNotFoundError(session_id)
        return stored.session.model_copy(deep=True)


def _normalize_git_status_path(path: str, git_root: Path, workspace_root: Path) -> str | None:
    """
    把 git status 输出路径归一为工作区相对路径。

    @params:
        path: git status 返回的原始路径
        git_root: git 仓库根目录
        workspace_root: LarkFlow 工作区根目录

    @return:
        路径位于工作区内时返回归一化结果，否则返回 None
    """
    raw_path = Path(path)
    absolute_path = raw_path if raw_path.is_absolute() else (git_root / raw_path)
    try:
        return str(absolute_path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        return None


def _parse_git_status_porcelain(output: str, git_root: Path, workspace_root: Path) -> list[str]:
    """
    解析 `git status --porcelain` 输出并筛出工作区内文件。

    @params:
        output: git status 原始输出
        git_root: git 仓库根目录
        workspace_root: LarkFlow 工作区根目录

    @return:
        返回去重后的工作区相对路径列表
    """
    files: list[str] = []
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        path = raw_line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path:
            continue
        normalized_path = _normalize_git_status_path(path, git_root, workspace_root)
        if normalized_path:
            files.append(normalized_path)
    return sorted(dict.fromkeys(files))


def _list_dirty_files() -> list[str]:
    """
    列出当前工作区中所有未提交的文件路径。

    @params:
        无

    @return:
        返回工作区相对路径列表
    """
    workspace_root = _workspace_root()
    git_root = _git_root()
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return _parse_git_status_porcelain(result.stdout, git_root, workspace_root)


def delivery_check(session_id: str) -> VisualEditDeliveryCheck:
    """
    检查已确认预览的文件是否适合直接提交。

    @params:
        session_id: 视觉编辑会话 ID

    @return:
        返回交付检查结果，包括文件范围和安全性判断
    """
    with _LOCK:
        stored = _SESSIONS.get(session_id)
        if stored is None:
            raise VisualEditNotFoundError(session_id)
        if stored.session.status != VisualEditSessionStatus.CONFIRMED:
            raise VisualEditRequestError("只有 confirmed 状态的会话可以执行交付检查。")
        confirmed_files = list(stored.session.confirmed_files or stored.session.changed_files)

    dirty_files = _list_dirty_files()
    confirmed_set = set(confirmed_files)
    # 对外只回显本次确认文件的名单，其他脏文件只给数量，避免在 UI 中暴露无关改动细节。
    deliverable_files = [path for path in dirty_files if path in confirmed_set]
    unrelated_dirty_count = sum(1 for path in dirty_files if path not in confirmed_set)
    safe_to_commit = bool(deliverable_files) and unrelated_dirty_count == 0

    return VisualEditDeliveryCheck(
        session_id=session_id,
        confirmed_files=confirmed_files,
        deliverable_files=deliverable_files,
        dirty_file_count=len(dirty_files),
        unrelated_dirty_count=unrelated_dirty_count,
        safe_to_commit=safe_to_commit,
    )


def prepare_commit(session_id: str) -> VisualEditCommitPlan:
    """
    基于交付检查结果生成一次提交计划，但不真正执行 git commit。

    @params:
        session_id: 视觉编辑会话 ID

    @return:
        返回包含文件范围、提交信息和警告的提交计划
    """
    with _LOCK:
        stored = _SESSIONS.get(session_id)
        if stored is None:
            raise VisualEditNotFoundError(session_id)
        if stored.session.status != VisualEditSessionStatus.CONFIRMED:
            raise VisualEditRequestError("只有 confirmed 状态的会话可以准备提交。")
        session = stored.session.model_copy(deep=True)

    check = delivery_check(session_id)
    warnings: list[str] = []
    if not check.deliverable_files:
        warnings.append("本次视觉编辑文件当前不在 git 未提交变更中。")
    if check.unrelated_dirty_count:
        warnings.append(f"当前工作区还有 {check.unrelated_dirty_count} 个其他未提交改动。")
    if not check.safe_to_commit:
        warnings.append("自动提交前需要人工确认文件范围。")

    summary = session.delivery_summary or _build_delivery_summary(session)
    return VisualEditCommitPlan(
        session_id=session_id,
        files=check.deliverable_files,
        commit_message=_build_commit_message(session),
        summary=summary,
        safe_to_commit=check.safe_to_commit,
        requires_manual_confirmation=not check.safe_to_commit,
        warnings=warnings,
    )


def _repo_relative_paths(files: list[str]) -> list[str]:
    """
    把工作区相对路径转换成 git 仓库相对路径。

    @params:
        files: 工作区相对路径列表

    @return:
        返回 git 仓库相对路径列表
    """
    git_root = _git_root().resolve()
    workspace_root = _workspace_root().resolve()
    paths: list[str] = []
    for raw_path in files:
        absolute_path = (workspace_root / raw_path).resolve()
        try:
            paths.append(str(absolute_path.relative_to(git_root)))
        except ValueError as exc:
            raise VisualEditRequestError(f"提交文件不在 git 仓库内: {raw_path}") from exc
    return paths


def _read_commit_hash(repo_root: Path) -> str:
    """
    读取当前 HEAD 的提交哈希。

    @params:
        repo_root: git 仓库根目录

    @return:
        返回 HEAD 对应的 commit hash
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def commit_visual_edit(session_id: str, *, force: bool = False) -> VisualEditCommitResult:
    """
    只提交当前视觉编辑确认过的文件。

    @params:
        session_id: 视觉编辑会话 ID
        force: 工作区仍有其他脏文件时是否强制继续提交

    @return:
        返回提交结果，包括 commit hash 和实际提交文件
    """
    plan = prepare_commit(session_id)
    if not plan.files:
        raise VisualEditRequestError("没有可提交的视觉编辑文件。")
    if plan.requires_manual_confirmation and not force:
        raise VisualEditRequestError("当前工作区存在其他未提交改动；如确认只提交本次文件，请显式 force。")

    git_root = _git_root()
    # GitTool 只 add 本次确认文件，避免把用户工作区里的其他改动一起提交。
    repo_files = _repo_relative_paths(plan.files)
    try:
        result = GitTool(git_root).commit_files(repo_files, plan.commit_message)
    except GitToolError as exc:
        raise VisualEditRequestError(str(exc)) from exc

    if result.stdout == "No staged changes to commit":
        raise VisualEditRequestError("没有 staged 变更可提交。")

    return VisualEditCommitResult(
        session_id=session_id,
        commit_hash=_read_commit_hash(git_root),
        commit_message=plan.commit_message,
        committed_files=plan.files,
        warnings=plan.warnings,
    )


def confirm_preview(session_id: str) -> VisualEditSession:
    """
    确认预览结果，并把当前修改转成可交付状态。

    @params:
        session_id: 视觉编辑会话 ID

    @return:
        返回确认后的会话快照
    """
    with _LOCK:
        stored = _SESSIONS.get(session_id)
        if stored is None:
            raise VisualEditNotFoundError(session_id)
        if stored.session.status == VisualEditSessionStatus.CONFIRMED:
            return stored.session.model_copy(deep=True)
        if stored.session.status != VisualEditSessionStatus.PREVIEW_READY:
            raise VisualEditRequestError("只有 preview_ready 状态的会话可以确认。")
        stored.session.status = VisualEditSessionStatus.CONFIRMING
        stored.session.updated_at = _now()
        stored.session.confirmed_files = list(stored.session.changed_files)
        stored.session.delivery_summary = _build_delivery_summary(stored.session)
        stored.session.status = VisualEditSessionStatus.CONFIRMED
        stored.session.updated_at = _now()
        # 确认后把当前文件视为新的工作区基线，因此不再保留回滚快照。
        stored.snapshots.clear()
        return stored.session.model_copy(deep=True)


def cancel_preview(session_id: str) -> VisualEditSession:
    """
    取消预览，并把已落盘的临时改动恢复到原始内容。

    @params:
        session_id: 视觉编辑会话 ID

    @return:
        返回取消后的会话快照
    """
    with _LOCK:
        stored = _SESSIONS.get(session_id)
        if stored is None:
            raise VisualEditNotFoundError(session_id)
        if stored.session.status == VisualEditSessionStatus.CANCELLED:
            return stored.session.model_copy(deep=True)
        if stored.session.status not in (
            VisualEditSessionStatus.EDITING,
            VisualEditSessionStatus.PREVIEW_READY,
            VisualEditSessionStatus.FAILED,
        ):
            raise VisualEditRequestError("当前会话状态不支持取消。")
        stored.session.status = VisualEditSessionStatus.CANCELLING
        stored.session.updated_at = _now()
        _restore_locked(stored)
        stored.snapshots.clear()
        stored.session.status = VisualEditSessionStatus.CANCELLED
        stored.session.error = None
        stored.session.updated_at = _now()
        return stored.session.model_copy(deep=True)
