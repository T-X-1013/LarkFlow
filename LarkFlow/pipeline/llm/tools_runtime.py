"""
LarkFlow 本地工具运行时

负责：
1. 接收 Agent 发起的工具调用
2. 在统一上下文中执行 inspect_db、file_editor、run_bash
3. 对文件工具施加读写边界，避免 Agent 误改框架代码
"""

import os
import re
import signal
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from pipeline.config import runtime as runtime_config
from telemetry.otel import start_span


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

# inspect_db 只允许这些前缀开头的只读查询，避免设计阶段误执行写库语句
READ_ONLY_SQL_PREFIXES = ("select", "show", "pragma", "describe", "explain", "with")

# 兼容 MySQL 风格的 SHOW CREATE TABLE，在 SQLite 下改写到 sqlite_master
SQLITE_SHOW_CREATE_TABLE_RE = re.compile(r"^\s*show\s+create\s+table\s+([A-Za-z_][\w]*)\s*;?\s*$", re.IGNORECASE)

# 兼容 MySQL 风格的 DESCRIBE，在 SQLite 下统一映射到 PRAGMA table_info
SQLITE_DESCRIBE_TABLE_RE = re.compile(r"^\s*describe\s+([A-Za-z_][\w]*)\s*;?\s*$", re.IGNORECASE)

# 兼容 MySQL 风格的 SHOW COLUMNS FROM，在 SQLite 下同样映射到 PRAGMA table_info
SQLITE_SHOW_COLUMNS_RE = re.compile(
    r"^\s*show\s+columns\s+from\s+([A-Za-z_][\w]*)\s*;?\s*$",
    re.IGNORECASE,
)

# 兼容 SHOW TABLES，让 Agent 不需要感知 SQLite 和 MySQL 的元数据查询差异
SQLITE_SHOW_TABLES_RE = re.compile(r"^\s*show\s+tables\s*;?\s*$", re.IGNORECASE)


@dataclass
class ToolContext:
    """
    描述单次需求执行时的工具运行上下文

    @params:
        demand_id: 当前需求 ID
        workspace_root: 允许读取项目上下文的工作区根目录
        target_dir: 允许写入本次需求产物的目标目录
        logger: 结构化 logger；未接入时允许为空

    @return:
        返回 ToolContext 实例，供各工具执行函数共享运行时边界
    """
    demand_id: str               # 当前需求 ID
    workspace_root: str          # 允许读取项目上下文的工作区根目录
    target_dir: str              # 允许写入本次需求产物的目标目录
    logger: Any = None           # 结构化 logger；未接入时回退到 print
    phase: Optional[str] = None
    # Skill 闸门用：每次 file_editor read 成功时把 skills/ 前缀的相对路径写进来。
    # engine 层在每轮工具执行后把集合回写到 session["skills_read"] 持久化。
    skills_read: Optional[set] = None


def _record_skill_read_if_applicable(path: Path, ctx: ToolContext) -> None:
    """file_editor read 成功且落在 workspace_root/skills/*.md 时记入已读集。

    规则：
    - ctx.skills_read 为 None 表示调用方不关心闸门，不做任何事。
    - 非 workspace_root 下文件忽略（外部文件不属于 skill）。
    - 仅收 skills/ 前缀的 .md 文件。
    - 写入路径用相对 workspace_root 的 POSIX 风格，与路由器产出的 skill 路径对齐。
    """
    if ctx.skills_read is None:
        return
    try:
        workspace = Path(ctx.workspace_root).resolve()
        resolved = path.resolve()
        relative = resolved.relative_to(workspace)
    except (ValueError, OSError):
        return
    parts = relative.parts
    if not parts or parts[0] != "skills":
        return
    if resolved.suffix.lower() != ".md":
        return
    ctx.skills_read.add(relative.as_posix())


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

    # 当前 Prompt 仍会传入 ../demo-app 这类相对路径，因此这里只做标准化，
    # 是否允许访问要交给后续的读写白名单判断
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
        # 测试、构建等命令默认应该作用于当前需求产物，而不是框架目录
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
        # 这里不尝试做完整 shell 审计，只优先挡住事故率最高的高危命令组合
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
            # 必须杀掉整棵进程树，否则 bash 拉起的子进程可能残留在后台继续运行
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        merged_stdout = (exc.stdout or "") + (stdout or "")
        merged_stderr = (exc.stderr or "") + (stderr or "")
        return _format_bash_result(merged_stdout, merged_stderr, timeout_seconds=timeout_seconds)

    return _format_bash_result(stdout, stderr, exit_code=process.returncode)


def _get_database_url() -> str:
    """
    读取数据库连接串

    @params:
        无入参

    @return:
        返回环境变量中的 DATABASE_URL；若未配置则抛出异常
    """
    database_url = runtime_config.database_url()
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    return database_url


def _validate_read_only_query(query: str) -> str:
    """
    校验 inspect_db 只执行只读查询

    @params:
        query: 调用方传入的 SQL 文本

    @return:
        返回去除首尾空白后的查询文本；若查询为空或不是只读语句则抛出异常
    """
    normalized = (query or "").strip()
    if not normalized:
        raise ValueError("Missing required argument: query")

    lowered = normalized.lower()
    if not lowered.startswith(READ_ONLY_SQL_PREFIXES):
        raise ValueError("inspect_db only supports read-only schema or select queries")

    return normalized


def _resolve_sqlite_database_path(database_url: str, ctx: ToolContext) -> Path:
    """
    解析 SQLite 数据库文件路径

    @params:
        database_url: sqlite 协议的 DATABASE_URL
        ctx: 当前需求的运行时上下文

    @return:
        返回数据库文件的绝对路径；相对路径默认相对于仓库根解析
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(f"Unsupported SQLite DATABASE_URL: {database_url}")

    remainder = database_url[len(prefix):]
    if not remainder:
        raise ValueError(f"Invalid SQLite DATABASE_URL: {database_url}")

    if remainder.startswith("/"):
        db_path = Path("/" + remainder.lstrip("/"))
    else:
        repo_root = Path(ctx.workspace_root).resolve().parent
        db_path = repo_root / remainder

    resolved = db_path.resolve(strict=False)
    if not resolved.exists():
        raise FileNotFoundError(f"SQLite database file does not exist: {resolved}")
    return resolved


def _normalize_sqlite_query(query: str) -> tuple[str, tuple]:
    """
    将常见的 MySQL 风格 schema 查询转换为 SQLite 可执行语句

    @params:
        query: 调用方传入的查询文本

    @return:
        返回标准化后的 SQL 语句与参数元组
    """
    if match := SQLITE_SHOW_CREATE_TABLE_RE.match(query):
        table_name = match.group(1)
        # SQLite 没有 SHOW CREATE TABLE，需改写到 sqlite_master 才能拿到真实建表语句
        return (
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )

    if match := SQLITE_DESCRIBE_TABLE_RE.match(query):
        table_name = match.group(1)
        # DESCRIBE / SHOW COLUMNS 属于 MySQL 风格语法，在 SQLite 下统一映射到 PRAGMA table_info
        return (f"PRAGMA table_info({table_name})", ())

    if match := SQLITE_SHOW_COLUMNS_RE.match(query):
        table_name = match.group(1)
        return (f"PRAGMA table_info({table_name})", ())

    if SQLITE_SHOW_TABLES_RE.match(query):
        # SHOW TABLES 同样需要改写成 sqlite_master 查询，避免要求 Agent 学会引擎差异
        return (
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
            (),
        )

    return (query, ())


def _stringify_db_value(value: Any) -> str:
    """
    将数据库值转换为可读文本

    @params:
        value: 数据库返回的单个值

    @return:
        返回适合放入文本结果中的字符串
    """
    if value is None:
        return "NULL"
    return str(value)


def _format_db_rows(engine_name: str, query: str, columns: list[str], rows: list[tuple]) -> str:
    """
    将数据库查询结果格式化为稳定文本

    @params:
        engine_name: 数据库引擎名称，例如 sqlite 或 mysql
        query: 执行后的原始查询文本
        columns: 结果列名列表
        rows: 查询返回的记录列表

    @return:
        返回适合 Agent 消费的结构化文本
    """
    lines = [
        f"DATABASE: {engine_name}",
        f"QUERY: {query}",
        "",
        "COLUMNS:",
    ]

    if columns:
        lines.extend(f"- {column}" for column in columns)
    else:
        lines.append("- <none>")

    lines.extend(["", "ROWS:"])

    if not rows:
        # 空结果也要显式返回，避免 Agent 把“查询成功但无数据”和“工具失败”混在一起
        lines.append("- <empty>")
        return "\n".join(lines)

    for row in rows:
        row_dict = dict(zip(columns, row)) if columns else {"value": row}
        first_item = True
        for key, value in row_dict.items():
            prefix = "- " if first_item else "  "
            lines.append(f"{prefix}{key}: {_stringify_db_value(value)}")
            first_item = False

    return "\n".join(lines)


def _execute_sqlite_query(query: str, database_url: str, ctx: ToolContext) -> str:
    """
    在 SQLite 上执行 inspect_db 查询

    @params:
        query: 已通过只读校验的查询文本
        database_url: sqlite 协议的 DATABASE_URL
        ctx: 当前需求的运行时上下文

    @return:
        返回格式化后的查询结果文本
    """
    db_path = _resolve_sqlite_database_path(database_url, ctx)
    normalized_query, parameters = _normalize_sqlite_query(query)

    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute(normalized_query, parameters)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description] if cursor.description else []

    return _format_db_rows("sqlite", normalized_query, columns, [tuple(row) for row in rows])


def _build_mysql_connection_kwargs(database_url: str) -> dict:
    """
    将 MySQL DATABASE_URL 解析为连接参数

    @params:
        database_url: mysql 或 mysql+pymysql 协议的 DATABASE_URL

    @return:
        返回可直接传给 pymysql.connect 的参数字典
    """
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError(f"Unsupported MySQL DATABASE_URL: {database_url}")

    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise ValueError(f"Invalid MySQL DATABASE_URL: {database_url}")

    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database_name,
        "charset": "utf8mb4",
    }


def _execute_mysql_query(query: str, database_url: str) -> str:
    """
    在 MySQL 上执行 inspect_db 查询

    @params:
        query: 已通过只读校验的查询文本
        database_url: mysql 协议的 DATABASE_URL

    @return:
        返回格式化后的查询结果文本；若缺少客户端依赖则抛出异常
    """
    try:
        import pymysql
    except ModuleNotFoundError as exc:
        # 这里返回清晰错误而不是回退到伪造数据，避免 Phase 1 在错误 schema 上继续设计
        raise RuntimeError("MySQL DATABASE_URL detected, but PyMySQL is not installed") from exc

    connection_kwargs = _build_mysql_connection_kwargs(database_url)
    connection = pymysql.connect(
        **connection_kwargs,
        cursorclass=pymysql.cursors.Cursor,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description] if cursor.description else []
    finally:
        connection.close()

    return _format_db_rows("mysql", query, columns, list(rows))


def _execute_inspect_db(query: str, ctx: ToolContext) -> str:
    """
    执行真实数据库结构查询

    @params:
        query: 调用方传入的查询文本
        ctx: 当前需求的运行时上下文

    @return:
        返回 SQLite 或 MySQL 的真实查询结果文本
    """
    database_url = _get_database_url()
    normalized_query = _validate_read_only_query(query)

    if database_url.startswith("sqlite:///"):
        return _execute_sqlite_query(normalized_query, database_url, ctx)

    if database_url.startswith(("mysql://", "mysql+pymysql://")):
        # MySQL 直接执行真实只读查询；调用方可以用 SHOW CREATE TABLE，也可以自己查 information_schema
        return _execute_mysql_query(normalized_query, database_url)

    raise ValueError(f"Unsupported DATABASE_URL scheme: {database_url}")


def execute(tool_name: str, args: dict, ctx: ToolContext) -> str:
    """
    执行本地工具调用，并返回可回填给 Agent 的文本结果

    @params:
        tool_name: 工具名称，例如 inspect_db、file_editor、run_bash
        args: 工具参数字典
        ctx: 当前需求的运行时上下文，包含工作区与目标产物目录

    @return:
        返回字符串结果；成功时返回工具输出，失败时返回可读的错误文本
    """
    _log(ctx, f"  [Tool Execution] 正在执行 {tool_name}，参数: {args}")
    started_at = time.monotonic()
    result_text = ""

    with start_span(
        "tool.execute",
        {
            "demand_id": ctx.demand_id,
            "phase": ctx.phase,
            "tool.name": tool_name,
        },
    ) as span:
        if tool_name == "inspect_db":
            # 设计阶段依赖这个工具理解现有数据结构；这里返回真实 schema，而不是继续伪造占位数据
            try:
                query = args.get("query", "")
                result_text = _execute_inspect_db(query, ctx)
            except Exception as e:
                result_text = f"Inspect DB failed: {str(e)}"
        elif tool_name == "file_editor":
            # file_editor 统一承接受控文件访问：可读项目上下文与目标代码，只可写目标产物目录
            action = args.get("action")
            span.set_attribute("tool.action", action)
            try:
                path = _resolve_tool_path(args.get("path", ""), ctx)
                span.set_attribute("tool.path", str(path))
                if action == "read":
                    _ensure_read_allowed(path, ctx)
                    result_text = path.read_text(encoding="utf-8")
                    _record_skill_read_if_applicable(path, ctx)
                elif action == "list_dir":
                    _ensure_read_allowed(path, ctx)
                    if not path.is_dir():
                        raise ValueError(f"Not a directory: {path}")
                    result_text = "\n".join(sorted(item.name for item in path.iterdir()))
                elif action == "write":
                    _ensure_write_allowed(path, ctx)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(args.get("content", ""), encoding="utf-8")
                    result_text = f"Successfully wrote to {path}"
                elif action == "replace":
                    _ensure_write_allowed(path, ctx)
                    result_text = _replace_file_content(
                        path,
                        args.get("old_content"),
                        args.get("content", ""),
                    )
                else:
                    result_text = f"Unsupported file_editor action: {action}"
            except Exception as e:
                result_text = f"File operation failed: {str(e)}"
        elif tool_name == "run_bash":
            # run_bash 负责测试、构建等命令执行，并补充 cwd 约束、危险命令拦截、真实超时终止和输出截断
            try:
                cmd = args.get("command", "")
                cwd = _resolve_bash_cwd(args.get("cwd"), ctx)
                span.set_attribute("tool.cwd", str(cwd))
                _ensure_bash_cwd_allowed(cwd, ctx)
                _validate_bash_command(cmd)
                timeout_seconds = _resolve_bash_timeout(args.get("timeout"))
                span.set_attribute("tool.timeout_seconds", timeout_seconds)
                result_text = _run_bash_command(cmd, cwd, timeout_seconds)
            except Exception as e:
                result_text = f"Command execution failed: {str(e)}"
        else:
            result_text = f"Unknown tool: {tool_name}"

        duration_ms = int((time.monotonic() - started_at) * 1000)
        span.set_attribute("tool.duration_ms", duration_ms)
        span.set_attribute("tool.success", not _looks_like_tool_failure(result_text))
        return result_text


def _looks_like_tool_failure(result_text: str) -> bool:
    prefixes = (
        "Inspect DB failed:",
        "File operation failed:",
        "Command execution failed:",
        "Unknown tool:",
        "Unsupported file_editor action:",
    )
    return (result_text or "").startswith(prefixes)
