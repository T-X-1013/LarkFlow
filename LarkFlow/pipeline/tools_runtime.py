import os
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContext:
    demand_id: str
    workspace_root: str
    target_dir: str
    logger: Any = None


def _log(ctx: ToolContext, message: str) -> None:
    if ctx.logger is not None:
        try:
            ctx.logger.info(message)
            return
        except Exception:
            pass
    print(message)


def execute(tool_name: str, args: dict, ctx: ToolContext) -> str:
    """
    在本地或 Docker 容器中实际执行 Agent 调用的工具。
    B0 阶段仅做抽离，保持现有行为不变。
    """
    _log(ctx, f"  [Tool Execution] 正在执行 {tool_name}，参数: {args}")

    if tool_name == "mock_db":
        query = args.get("query", "")
        # 这里可以接入真实的 MySQL/TiDB 查询逻辑
        return f"Mock DB Result for '{query}': Table `users` has columns (id, name, created_at)."

    if tool_name == "file_editor":
        action = args.get("action")
        path = os.path.join(ctx.workspace_root, args.get("path", ""))

        try:
            if action == "read":
                with open(path, "r") as f:
                    return f.read()
            if action == "write":
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(args.get("content", ""))
                return f"Successfully wrote to {path}"
            if action == "list_dir":
                return "\n".join(os.listdir(path))
            return f"Unsupported file_editor action: {action}"
        except Exception as e:
            return f"File operation failed: {str(e)}"

    if tool_name == "run_bash":
        cmd = args.get("command", "")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    return f"Unknown tool: {tool_name}"
