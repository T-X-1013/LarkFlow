"""
LarkFlow 本地工具运行时

负责：
1. 接收 Agent 发起的工具调用
2. 在统一上下文中执行 mock_db、file_editor、run_bash
3. 对文件工具施加读写边界，避免 Agent 误改框架代码
"""

import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# run_bash 的默认超时时间
DEFAULT_BASH_TIMEOUT_SECONDS = 60

# run_bash 可接受的最大超时时间
MAX_BASH_TIMEOUT_SECONDS = 300

# stdout / stderr 的单路最大输出大小
MAX_BASH_OUTPUT_BYTES = 100 * 1024

# 这些规则只用于粗粒度降低事故率，不追求覆盖全部 shell 攻击面
FORBIDDEN_BASH_PATTERNS = (
    (re.compile(r"\brm\s+-rf\s+/(\s|$)"), "rm -rf /"),
    (re.compile(r":\(\)\s*\{\s*:\|\:&\s*;\s*\}\s*;?\s*:"), "fork bomb"),
    (re.compile(r"\bsudo\b"), "sudo"),
    (re.compile(r"\bcurl\b[^\n|]*\|\s*(?:sh|bash)\b"), "curl | sh"),
    (re.compile(r"\bwget\b[^\n|]*\|\s*(?:sh|bash)\b"), "wget | sh"),
    (re.compile(r"(?:^|[\s;|&])tee\b[^\n]*(?:/etc|/usr)\b"), "write to /etc or /usr via tee"),
    (re.compile(r"(?:>|>>)\s*/(?:etc|usr)\b"), "redirect write to /etc or /usr"),
    (re.compile(r"\b(?:cp|mv|install|touch|mkdir|chmod|chown|rm)\b[^\n]*(?:/etc|/usr)\b"), "write to /etc or /usr"),
)


@dataclass
class ToolContext:
    demand_id: str       # 当前需求 ID
    workspace_root: str  # 允许读取项目上下文的工作区根目录
    target_dir: str      # 允许写入本次需求产物的目标目录
    logger: Any = None   # 结构化 logger；未接入时回退到 print


def _log(ctx: ToolContext, message: str) -> None:
    """
    输出工具运行时日志

    @params:
        ctx: 当前需求的运行时上下文
        message: 需要输出的日志文本

    @return:
        无返回值；优先写入结构化 logger，失败时回退到 stdout
    """
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

    @params:
        raw_path: 工具传入的相对路径字符串
        ctx: 当前需求的运行时上下文

    @return:
        返回相对于 workspace_root 解析后的绝对路径
    """
    if not raw_path:
        raise ValueError("Missing required argument: path")

    requested = Path(raw_path)
    if requested.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    return (Path(ctx.workspace_root) / requested).resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    """
    判断解析后的真实路径是否落在指定根目录内

    @params:
        path: 待检查的绝对路径
        root: 允许访问的根目录

    @return:
        如果 path 位于 root 内则返回 True，否则返回 False
    """
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

    @params:
        path: 已完成标准化的目标路径
        ctx: 当前需求的运行时上下文

    @return:
        无返回值；若路径不在允许读取的范围内则抛出异常
    """
    workspace_root = Path(ctx.workspace_root).resolve()
    target_dir = Path(ctx.target_dir).resolve()

    if _is_within(path, workspace_root) or _is_within(path, target_dir):
        return

    raise PermissionError(f"Read access denied: {path}")


def _ensure_write_allowed(path: Path, ctx: ToolContext) -> None:
    """
    校验写操作是否允许执行

    @params:
        path: 已完成标准化的目标路径
        ctx: 当前需求的运行时上下文

    @return:
        无返回值；若路径不在 target_dir 内则抛出异常
    """
    target_dir = Path(ctx.target_dir).resolve()

    if _is_within(path, target_dir):
        return

    raise PermissionError(f"Write access denied outside target_dir: {path}")


def _replace_file_content(path: Path, old_content: str, new_content: str) -> str:
    """
    执行精确一次的文本替换

    replace 的目标是降低误改风险，因此 old_content 必须恰好命中 1 次；
    0 次说明调用方读取的旧状态已经失效，>1 次说明锚点不够精确

    @params:
        path: 需要执行替换的目标文件路径
        old_content: 调用方预期文件中已存在的旧文本
        new_content: 准备写回文件的新文本

    @return:
        返回替换成功后的提示文本；如果 old_content 不满足唯一命中则抛出异常
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


def _resolve_bash_cwd(raw_cwd: str, ctx: ToolContext) -> Path:
    """
    解析 run_bash 的工作目录

    未显式指定 cwd 时默认进入 target_dir，便于测试、构建等命令直接作用于当前需求产物

    @params:
        raw_cwd: 工具传入的工作目录字符串；允许为空
        ctx: 当前需求的运行时上下文

    @return:
        返回标准化后的工作目录绝对路径
    """
    if raw_cwd in (None, ""):
        path = Path(ctx.target_dir).resolve()
    else:
        requested = Path(raw_cwd)
        if requested.is_absolute():
            raise ValueError("Absolute cwd is not allowed")
        path = (Path(ctx.workspace_root) / requested).resolve(strict=False)

    if not path.exists():
        raise ValueError(f"Working directory does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Working directory is not a directory: {path}")
    return path


def _ensure_bash_cwd_allowed(path: Path, ctx: ToolContext) -> None:
    """
    run_bash 允许在两类目录执行命令：
    1. workspace_root：便于读取项目规则、脚本或仓库级上下文
    2. target_dir：便于测试、构建和运行当前需求产物

    @params:
        path: 已解析完成的工作目录
        ctx: 当前需求的运行时上下文

    @return:
        无返回值；若 cwd 越过允许的目录边界则抛出异常
    """
    workspace_root = Path(ctx.workspace_root).resolve()
    target_dir = Path(ctx.target_dir).resolve()

    if _is_within(path, workspace_root) or _is_within(path, target_dir):
        return

    raise PermissionError(f"Working directory access denied: {path}")


def _resolve_bash_timeout(raw_timeout: Any) -> int:
    """
    解析并收敛 run_bash 的超时时间

    @params:
        raw_timeout: 工具传入的超时参数；允许为空

    @return:
        返回经过默认值与上限收敛后的秒数
    """
    if raw_timeout in (None, ""):
        return DEFAULT_BASH_TIMEOUT_SECONDS

    timeout_seconds = int(raw_timeout)
    if timeout_seconds <= 0:
        raise ValueError("timeout must be a positive integer")

    return min(timeout_seconds, MAX_BASH_TIMEOUT_SECONDS)


def _validate_bash_command(command: str) -> None:
    """
    基于黑名单做粗粒度命令拦截

    目标是挡住明显危险的命令组合，而不是实现完整 shell 审计系统

    @params:
        command: 待执行的 bash 命令文本

    @return:
        无返回值；命中黑名单或命令为空时抛出异常
    """
    if not command or not command.strip():
        raise ValueError("Missing required argument: command")

    for pattern, label in FORBIDDEN_BASH_PATTERNS:
        if pattern.search(command):
            raise PermissionError(f"Command rejected by safety policy: matched forbidden pattern '{label}'")


def _truncate_output(text: str, max_bytes: int = MAX_BASH_OUTPUT_BYTES) -> str:
    """
    按字节数截断输出，避免超长 stdout / stderr 污染上下文

    @params:
        text: 待截断的原始输出文本
        max_bytes: 允许保留的最大字节数

    @return:
        返回原始文本或带截断标记的文本
    """
    if text is None:
        return ""

    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text

    truncated = raw[:max_bytes].decode("utf-8", errors="ignore")
    return f"{truncated}\n... [truncated]"


def _format_bash_result(stdout: str, stderr: str, exit_code: int = None, timeout_seconds: int = None) -> str:
    """
    统一 run_bash 返回格式，便于后续模型消费

    @params:
        stdout: 命令执行后的标准输出
        stderr: 命令执行后的标准错误
        exit_code: 命令退出码；超时时允许为空
        timeout_seconds: 超时时间；仅在超时场景下传入

    @return:
        返回统一格式的字符串结果
    """
    stdout_text = _truncate_output(stdout or "")
    stderr_text = _truncate_output(stderr or "")

    if timeout_seconds is not None:
        return f"Command timed out after {timeout_seconds}s\nSTDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}"

    return f"EXIT_CODE: {exit_code}\nSTDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}"


def _run_bash_command(command: str, cwd: Path, timeout_seconds: int) -> str:
    """
    执行 bash 命令，并在超时后杀掉整棵进程树

    start_new_session=True 用于让 timeout 后的 killpg 能覆盖 bash 及其子进程，
    避免留下后台睡眠、测试或构建进程

    @params:
        command: 需要执行的 bash 命令
        cwd: 命令执行所在的工作目录
        timeout_seconds: 允许执行的最大秒数

    @return:
        返回统一格式的命令执行结果；超时后返回超时信息与已收集的输出
    """
    process = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        merged_stdout = (exc.stdout or "") + (stdout or "")
        merged_stderr = (exc.stderr or "") + (stderr or "")
        return _format_bash_result(merged_stdout, merged_stderr, timeout_seconds=timeout_seconds)

    return _format_bash_result(stdout, stderr, exit_code=process.returncode)


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
        # run_bash 负责测试、构建等命令执行，并补充 cwd 约束、危险命令拦截、真实超时终止和输出截断
        try:
            cmd = args.get("command", "")
            cwd = _resolve_bash_cwd(args.get("cwd"), ctx)
            _ensure_bash_cwd_allowed(cwd, ctx)
            _validate_bash_command(cmd)
            timeout_seconds = _resolve_bash_timeout(args.get("timeout"))
            return _run_bash_command(cmd, cwd, timeout_seconds)
        except Exception as e:
            return f"Command execution failed: {str(e)}"

    return f"Unknown tool: {tool_name}"
