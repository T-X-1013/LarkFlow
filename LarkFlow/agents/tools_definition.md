<!-- AUTO-GENERATED, DO NOT EDIT -->

# Headless Agent Tools Definition

This file is generated from `pipeline/tools_schema.py` by `scripts/gen_tools_doc.py`.

These are the tools provided by the Pipeline for the LLM provider to call.

## 1. inspect_db
- **Description**: Connects to the project's database to query schema or data. Use this to understand existing table structures before proposing changes.
- **Parameters**:
  - `query` (string, required): The SQL query to execute (e.g., 'SHOW CREATE TABLE users', 'SELECT * FROM users LIMIT 1').

## 2. file_editor
- **Description**: A comprehensive tool for file operations in the workspace. Used to read existing code, write new files, modify existing files, or list directories.
- **Parameters**:
  - `action` (string, required, one of `read`, `write`, `replace`, `list_dir`): The file operation to perform. 'read' returns file contents. 'write' creates or overwrites a file. 'replace' replaces specific text in a file. 'list_dir' lists files in a directory.
  - `path` (string, required): The relative path to the file or directory in the workspace (e.g., 'src/main.go').
  - `content` (string, optional): The content to write or the text to replace. Required for 'write' and 'replace' actions.
  - `old_content` (string, optional): The exact old text to be replaced. Required ONLY for 'replace' action.

## 3. ask_human_approval
- **Description**: Suspends the AI agent and sends an interactive message card to the human reviewer via Lark (飞书). MUST be called at the end of the Design phase before any coding begins.
- **Parameters**:
  - `summary` (string, required): A brief, 1-2 sentence summary of the proposed technical design.
  - `design_doc` (string, required): The detailed technical design document in Markdown format, including goals, schema changes, API designs, and core logic flow.

## 4. run_bash
- **Description**: Executes a bash command in the project's Docker container or sandbox. Useful for running tests ('go test ./...'), building ('go build'), or managing dependencies ('go mod tidy').
- **Parameters**:
  - `command` (string, required): The bash command to run.
  - `cwd` (string, optional): Optional working directory, resolved relative to the workspace root. If omitted, the command runs in the current target project directory.
  - `timeout` (integer, optional): Optional timeout in seconds. Defaults to 60 and is capped at 300.
