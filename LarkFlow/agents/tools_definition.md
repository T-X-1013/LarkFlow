# Headless Agent Tools Definition

These are the tools provided by the Pipeline for the LLM provider to call.

## 1. inspect_db
- **Description**: Connects to the project's database to query schema or data.
- **Parameters**:
  - `query` (string): The SQL query to execute (e.g., `SHOW CREATE TABLE users`).

## 2. file_editor
- **Description**: A comprehensive tool for file operations in the workspace.
- **Parameters**:
  - `action` (string): One of `read`, `write`, `replace`, `list_dir`.
  - `path` (string): The relative path to the file or directory.
  - `content` (string, optional): The content to write or replace.
  - `old_content` (string, optional): The exact old text to be replaced. Required for `replace`.
- **Notes**:
  - `replace` only succeeds when `old_content` matches exactly once in the target file.

## 3. ask_human_approval
- **Description**: Suspends the AI agent and sends an interactive message card to the human reviewer via Lark (飞书).
- **Parameters**:
  - `summary` (string): A brief summary of the proposal.
  - `design_doc` (string): The detailed technical design document.

## 4. run_bash
- **Description**: Executes a bash command in the project's Docker container/sandbox. Useful for testing and building.
- **Parameters**:
  - `command` (string): The bash command to run (e.g., `go test ./...`, `go mod tidy`).
  - `cwd` (string, optional): The working directory, resolved relative to the workspace root. Defaults to the current target project directory.
  - `timeout` (integer, optional): Timeout in seconds. Defaults to `60` and is capped at `300`.
