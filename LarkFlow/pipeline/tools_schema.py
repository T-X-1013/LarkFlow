from typing import List, Dict, Any


def _get_tool_specs() -> List[Dict[str, Any]]:
    return [
        {
            "name": "mock_db",
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
                    }
                },
                "required": ["command"]
            }
        }
    ]


def get_anthropic_tools() -> List[Dict[str, Any]]:
    """
    Returns the list of tools formatted for the Anthropic API.
    These tools are used by the Headless Agent in different phases of the pipeline.
    """
    return [
        {
            "name": tool_spec["name"],
            "description": tool_spec["description"],
            "input_schema": tool_spec["schema"]
        }
        for tool_spec in _get_tool_specs()
    ]


def get_openai_tools() -> List[Dict[str, Any]]:
    """
    Returns the list of tools formatted for the OpenAI Responses API.
    These tools are used by the Headless Agent in different phases of the pipeline.
    """
    return [
        {
            "type": "function",
            "name": tool_spec["name"],
            "description": tool_spec["description"],
            "parameters": tool_spec["schema"],
            "strict": False
        }
        for tool_spec in _get_tool_specs()
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
