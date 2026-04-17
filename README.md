# LarkFlow

LarkFlow 是一个面向 Go 后端研发场景的无头多 Agent 工作流引擎。它用 Python Pipeline 串联设计、编码、测试、审查和部署阶段，并通过飞书卡片把“AI 先设计、人类审批、再进入实现”这条链路跑通。

当前仓库里有两个核心部分：

- `LarkFlow/`：工作流引擎本体，包含 Agent Prompt、规则库、技能库、LLM 适配层和飞书交互服务。
- `demo-app/`：当前工作区里的示例 Go 服务，现有 Agent Prompt 和部署逻辑默认都把它当作目标工程。

## 项目现状

这个仓库现在更适合被理解为“可跑通主流程的原型 / 实验框架”，而不是已经产品化的通用平台。代码已经具备以下主干能力：

- 支持 `Anthropic` 和 `OpenAI` 两种 LLM Provider。
- 通过四阶段 Agent Prompt 驱动需求设计、编码、测试和审查。
- 通过飞书交互卡片挂起审批，再由 Webhook 恢复流程。
- 能把设计规范拆分为 `rules/` 和 `skills/`，让编码 Agent 按需读取。
- 在流程结束后，默认尝试对 `demo-app/` 执行 Docker 构建和启动。

同时也有一些当前限制：

- `mock_db` 仍然只是演示用假实现，不会真正访问数据库。
- 会话状态保存在进程内存里，重启后会丢失。
- Python 引擎目录和仓库根目录是分离的，运行命令时需要明确工作目录。
- 部分辅助文档还没有完全跟上当前代码，本文档已按当前工作区实际情况重写。

## 流程概览

```text
新需求 -> Phase 1 设计 -> 飞书审批 -> Phase 2 编码 -> Phase 3 测试 -> Phase 4 审查 -> Docker 部署 demo-app
```

对应代码入口：

- 需求状态机：`LarkFlow/pipeline/engine.py`
- 飞书 Webhook 服务：`LarkFlow/pipeline/lark_interaction.py`
- 模型适配层：`LarkFlow/pipeline/llm_adapter.py`
- 工具 Schema：`LarkFlow/pipeline/tools_schema.py`

## 目录结构

```text
.
├── README.md
├── LarkFlow/
│   ├── .env.example
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── LarkFlow.md
│   ├── agents/
│   │   ├── phase1_design.md
│   │   ├── phase2_coding.md
│   │   ├── phase3_test.md
│   │   ├── phase4_review.md
│   │   └── tools_definition.md
│   ├── pipeline/
│   │   ├── engine.py
│   │   ├── lark_client.py
│   │   ├── lark_interaction.py
│   │   ├── llm_adapter.py
│   │   ├── tools_schema.py
│   │   └── utils/lark_doc.py
│   ├── rules/
│   └── skills/
└── demo-app/
    ├── main.go
    ├── go.mod
    ├── internal/
    └── db/migrations/
```

## LarkFlow 引擎结构

### 1. Agents

`LarkFlow/agents/` 里定义了四个阶段的 System Prompt：

- `phase1_design.md`：系统设计与审批前方案输出。
- `phase2_coding.md`：按 `rules/` 和 `skills/` 实现 Go 代码。
- `phase3_test.md`：补测试并运行验证。
- `phase4_review.md`：从规范角度复查并修正问题。

### 2. Rules 和 Skills

这部分是编码 Agent 的“检索式规范库”：

- `rules/flow-rule.md`：总规则，要求先查路由表再编码。
- `rules/skill-routing.md`：按数据库、Redis、HTTP、错误处理、并发等关键词，把任务映射到具体 skill。
- `skills/*.md`：团队约束和最佳实践，例如 SQL 注入防护、统一 JSON 响应、错误包装、并发安全。

### 3. Pipeline

`LarkFlow/pipeline/engine.py` 负责主状态机和工具执行：

- 通过 `start_new_demand()` 启动一个新需求。
- 在设计阶段调用 `ask_human_approval` 后挂起。
- 收到审批回调后，进入 Coding、Test、Review 阶段。
- 最后默认对仓库根下的 `demo-app/` 尝试构建 Docker 镜像并运行。

`LarkFlow/pipeline/llm_adapter.py` 统一了两类模型调用：

- `Anthropic Messages API`
- `OpenAI Responses API`

`LarkFlow/pipeline/lark_interaction.py` 提供 FastAPI Webhook 服务，负责：

- 接收飞书卡片按钮点击
- 接收“开始执行”这类 HTTP 触发
- 读取飞书文档链接内容
- 唤醒已挂起的 Pipeline

## demo-app 说明

当前工作区中的 `demo-app/` 已经是一个可测试的 Go 示例服务，不再只是空目录。它目前实现了一个最小用户年龄更新流程：

- HTTP 接口：`PUT /users/:id/age`
- 配置入口：`demo-app/internal/config/config.go`
- Handler / Service / Repository 分层
- SQLite 持久化
- 迁移脚本：`demo-app/db/migrations/001_add_age_to_users.sql`
- 多个单元测试文件

默认配置来自环境变量：

- `HTTP_ADDR`，默认 `:8080`
- `SQLITE_DSN`，默认 `file:demo.db?cache=shared&_foreign_keys=on`

## 快速开始

### 1. 安装 Python 依赖

在仓库根目录执行：

```bash
cd LarkFlow
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

复制并编辑 `LarkFlow/.env.example`：

```bash
cd LarkFlow
cp .env.example .env
```

核心变量如下：

```env
LLM_PROVIDER=anthropic

LARK_APP_ID=cli_xxx
LARK_APP_SECRET=xxx
LARK_CHAT_ID=ou_xxx
LARK_RECEIVE_ID_TYPE=open_id

ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_BASE_URL=
ANTHROPIC_MODEL=claude-sonnet-4-6

OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-codex
OPENAI_REASONING_EFFORT=medium
```

补充说明：

- `LLM_PROVIDER` 只能是 `anthropic` 或 `openai`。
- 如果你不用飞书开放平台发消息给 `open_id` / `chat_id`，也可以在本地环境中补充 `LARK_WEBHOOK_URL` 作为群机器人 webhook。
- 如果需求是飞书文档链接，读取文档内容时要求应用具备对应文档权限。

### 3. 启动方式

本项目有两种常用启动方式。

本地模拟一个需求全流程：

```bash
cd LarkFlow
python pipeline/engine.py
```

启动 FastAPI Webhook 服务：

```bash
cd LarkFlow
uvicorn pipeline.lark_interaction:app --host 0.0.0.0 --port 8000
```

注意：

- `pipeline/engine.py` 里的 `SESSION_STORE` 是进程内内存存储，只适合本地演示或单进程实验。
- 如果你从仓库根目录直接运行 Python 模块，路径相对关系容易出错，建议始终先 `cd LarkFlow`。

## 常用验证命令

验证 Python 依赖安装和入口是否可用：

```bash
cd LarkFlow
python -m py_compile pipeline/engine.py pipeline/lark_interaction.py pipeline/llm_adapter.py
```

验证示例 Go 服务：

```bash
cd demo-app
go test ./...
```

本地启动示例服务：

```bash
cd demo-app
go run .
```

## 当前推荐的使用方式

如果你是第一次接手这个仓库，建议按下面顺序理解：

1. 先看 `README.md`，明确仓库根目录和 `LarkFlow/` 子目录的关系。
2. 再看 `LarkFlow/LarkFlow.md`，快速理解模块职责。
3. 然后读 `LarkFlow/pipeline/engine.py` 和 `LarkFlow/pipeline/llm_adapter.py`，掌握主流程和 Provider 适配方式。
4. 最后再看 `agents/`、`rules/`、`skills/`，理解 Agent 是如何被约束的。

## 已知问题

按当前代码状态，以下问题仍然存在：

- `mock_db` 只返回固定文本，设计阶段不能依赖它做真实 schema 判断。
- `file_editor` 的文档与工具 schema 提到了 `replace`，但当前 `engine.py` 运行时并没有实现这个动作。
- `LarkFlow/Dockerfile` 里的启动命令仍然没有对齐当前 FastAPI 入口，容器化运行前需要先修正。

## 相关文档

- `LarkFlow/LarkFlow.md`：引擎模块速览。
- `LarkFlow/CHANGELOG.md`：版本变更记录。
- `LarkFlow/LOCAL_ISSUES_TRACKER.md`：本地问题跟踪，含部分历史结论，阅读时要以当前代码为准。
