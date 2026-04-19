"""
LarkFlow 本地工具运行时

负责：
1. 接收 Agent 发起的工具调用
2. 在统一上下文中执行 mock_db、file_editor、run_bash
3. 对文件工具施加读写边界，避免 Agent 误改框架代码
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolContext:
    demand_id: str       # 当前需求 ID
    workspace_root: str  # 允许读取项目上下文的工作区根目录
    target_dir: str      # 允许写入本次需求产物的目标目录
    logger: Any = None   # 结构化 logger；未接入时回退到 print


def _log(ctx: ToolContext, message: str) -> None:
    """优先走结构化日志；兼容旧流程时回退到 stdout """
    if ctx.logger is not None:
        try:
            ctx.logger.info(message)
            return
        except Exception:
            pass
    print(message)


def _resolve_tool_path(raw_path: str, ctx: ToolContext) -> Path:
    """
    将工具传入的相对路径标准化为绝对路径

    这里的职责只有“解析路径”，不负责决定这个路径是否允许访问
    真正的访问控制由后续的读写权限校验负责
    """
    if not raw_path:
        raise ValueError("Missing required argument: path")

    requested = Path(raw_path)
    if requested.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    return (Path(ctx.workspace_root) / requested).resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    """判断解析后的真实路径是否落在指定根目录内"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _ensure_read_allowed(path: Path, ctx: ToolContext) -> None:
    """
    读操作允许访问两类路径：
    1. workspace_root：规则、skills、agents 等项目上下文
    2. target_dir：当前需求产物代码，供编码、测试、审查阶段回读
    """
    workspace_root = Path(ctx.workspace_root).resolve()
    target_dir = Path(ctx.target_dir).resolve()

    if _is_within(path, workspace_root) or _is_within(path, target_dir):
        return

    raise PermissionError(f"Read access denied: {path}")


def _ensure_write_allowed(path: Path, ctx: ToolContext) -> None:
    """写操作仅允许落在 target_dir，避免 Agent 修改框架与规范文件。"""
    target_dir = Path(ctx.target_dir).resolve()

    if _is_within(path, target_dir):
        return

    raise PermissionError(f"Write access denied outside target_dir: {path}")


def _replace_file_content(path: Path, old_content: str, new_content: str) -> str:
    """
    执行精确一次的文本替换。

    replace 的目标是降低误改风险，因此 old_content 必须恰好命中 1 次；
    0 次说明调用方读取的旧状态已经失效，>1 次说明锚点不够精确
    """
    if old_content is None or old_content == "":
        raise ValueError("replace requires non-empty old_content")

    text = path.read_text(encoding="utf-8")
    occurrences = text.count(old_content)
    if occurrences == 0:
        raise ValueError("old_content not found")
    if occurrences > 1:
        raise ValueError("old_content matched multiple locations")

    updated = text.replace(old_content, new_content, 1)
    path.write_text(updated, encoding="utf-8")
    return f"Successfully replaced content in {path}"


def execute(tool_name: str, args: dict, ctx: ToolContext) -> str:
    """
    执行本地工具调用，并返回可回填给 Agent 的文本结果

    @params:
        tool_name: 工具名称，例如 mock_db、file_editor、run_bash
        args: 工具参数字典
        ctx: 当前需求的运行时上下文，包含工作区与目标产物目录

    @return:
        返回字符串结果；成功时返回工具输出，失败时返回可读的错误文本
    """
    _log(ctx, f"  [Tool Execution] 正在执行 {tool_name}，参数: {args}")

    if tool_name == "mock_db":
        query = args.get("query", "")
        # 设计阶段依赖这个工具理解现有数据结构；当前仍是占位实现，后续由 B3 接入真实 schema 查询
        # todo 这里可以接入真实的 MySQL/TiDB 查询逻辑
        return f"Mock DB Result for '{query}': Table `users` has columns (id, name, created_at)."

    if tool_name == "file_editor":
        # file_editor 统一承接受控文件访问：可读项目上下文与目标代码，只可写目标产物目录
        action = args.get("action")

        try:
            path = _resolve_tool_path(args.get("path", ""), ctx)
            if action == "read":
                # read 用于读取 rules/、skills/、agents/ 以及 target_dir 中的已有代码，供模型建立上下文
                _ensure_read_allowed(path, ctx)
                return path.read_text(encoding="utf-8")
            if action == "list_dir":
                # list_dir 只返回目录名列表，让模型先感知文件结构，再决定后续 read / write / replace
                _ensure_read_allowed(path, ctx)
                if not path.is_dir():
                    raise ValueError(f"Not a directory: {path}")
                return "\n".join(sorted(item.name for item in path.iterdir()))
            if action == "write":
                # write 适合新建文件或整体覆盖目标文件，例如生成 demo-app 下的新代码、测试或迁移文件
                # 代码产物只能写入 target_dir
                # rules/、skills/、pipeline/ 默认只读
                _ensure_write_allowed(path, ctx)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(args.get("content", ""), encoding="utf-8")
                return f"Successfully wrote to {path}"
            if action == "replace":
                # replace 适合小范围精确修改已有文件，要求调用方先读取文件，再提交唯一命中的 old_content
                # replace 与 write 共享同一写权限边界，只允许改目标产物目录内的文件
                _ensure_write_allowed(path, ctx)
                return _replace_file_content(
                    path,
                    args.get("old_content"),
                    args.get("content", ""),
                )
            return f"Unsupported file_editor action: {action}"
        except Exception as e:
            return f"File operation failed: {str(e)}"

    if tool_name == "run_bash":
        cmd = args.get("command", "")
        # run_bash 负责测试、构建等命令执行
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    return f"Unknown tool: {tool_name}"
