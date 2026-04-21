"""
LarkFlow 工具定义唯一源

负责：
1. 声明 Pipeline 暴露给模型的工具清单
2. 将同一份工具定义适配到 Anthropic 与 OpenAI 协议
3. 为工具文档生成脚本提供稳定输入
"""

from typing import Any, Dict, List


def get_tool_specs() -> List[Dict[str, Any]]:
    """
    返回 Pipeline 的原始工具定义列表

    @params:
        无入参

    @return:
        返回工具定义列表；这是工具协议与文档生成的唯一真相源
    """
    return [
        {
            "name": "inspect_db",
            "description": "Connects to the project's database to query schema or data. Use this to understand existing table structures before proposing changes.",
            "schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute (e.g., 'SHOW CREATE TABLE users', 'SELECT * FROM users LIMIT 1')."
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "file_editor",
            "description": "A comprehensive tool for file operations in the workspace. Used to read existing code, write new files, modify existing files, or list directories.",
            "schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "replace", "list_dir"],
                        "description": "The file operation to perform. 'read' returns file contents. 'write' creates or overwrites a file. 'replace' replaces specific text in a file. 'list_dir' lists files in a directory."
                    },
                    "path": {
                        "type": "string",
                        "description": "The relative path to the file or directory in the workspace (e.g., 'src/main.go')."
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write or the text to replace. Required for 'write' and 'replace' actions."
                    },
                    "old_content": {
                        "type": "string",
                        "description": "The exact old text to be replaced. Required ONLY for 'replace' action."
                    }
                },
                "required": ["action", "path"]
            }
        },
        {
            "name": "ask_human_approval",
            "description": "Suspends the AI agent and sends an interactive message card to the human reviewer via Lark (飞书). MUST be called at the end of the Design phase before any coding begins.",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "A brief, 1-2 sentence summary of the proposed technical design."
                    },
                    "design_doc": {
                        "type": "string",
                        "description": "The detailed technical design document in Markdown format, including goals, schema changes, API designs, and core logic flow."
                    }
                },
                "required": ["summary", "design_doc"]
            }
        },
        {
            "name": "run_bash",
            "description": "Executes a bash command in the project's Docker container or sandbox. Useful for running tests ('go test ./...'), building ('go build'), or managing dependencies ('go mod tidy').",
            "schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run."
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory, resolved relative to the workspace root. If omitted, the command runs in the current target project directory."
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Optional timeout in seconds. Defaults to 60 and is capped at 300."
                    }
                },
                "required": ["command"]
            }
        }
    ]


def get_anthropic_tools() -> List[Dict[str, Any]]:
    """
    将工具定义转换为 Anthropic API 所需格式

    @params:
        无入参

    @return:
        返回可直接传给 Anthropic Messages API 的 tools 列表
    """
    return [
        {
            "name": tool_spec["name"],
            "description": tool_spec["description"],
            "input_schema": tool_spec["schema"]
        }
        for tool_spec in get_tool_specs()
    ]


def get_openai_tools() -> List[Dict[str, Any]]:
    """
    将工具定义转换为 OpenAI Responses API 所需格式

    @params:
        无入参

    @return:
        返回可直接传给 OpenAI Responses API 的 tools 列表
    """
    return [
        {
            "type": "function",
            "name": tool_spec["name"],
            "description": tool_spec["description"],
            "parameters": tool_spec["schema"],
            "strict": False
        }
        for tool_spec in get_tool_specs()
    ]


def get_chat_completion_tools() -> List[Dict[str, Any]]:
    """
    Returns the tools formatted for OpenAI-compatible Chat Completions APIs.
    DashScope/Qwen currently exposes its OpenAI-compatible tool calling through
    the Chat Completions shape rather than the Responses API shape.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool_spec["name"],
                "description": tool_spec["description"],
                "parameters": tool_spec["schema"],
            },
        }
        for tool_spec in get_tool_specs()
    ]

# Example of how to use this with the Anthropic Python SDK:
#
# import anthropic
# client = anthropic.Anthropic()
#
# response = client.messages.create(
#     model="claude-3-5-sonnet-20240620",
#     max_tokens=4096,
#     system="You are an Autonomous AI System Architect...",
#     messages=[
#         {"role": "user", "content": "We need to add a user registration feature."}
#     ],
#     tools=get_anthropic_tools()
# )
