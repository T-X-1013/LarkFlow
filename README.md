# LarkFlow Framework

LarkFlow 已经从一个依赖本地 IDE 插件的工具，进化为一个**完全无头（Headless）、基于多智能体（Multi-Agent）协作的自动化研发工作流引擎**。

[![Version](https://img.shields.io/badge/version-1.3.1-blue.svg)](https://github.com/your-repo/larkflow)
[![Architecture](https://img.shields.io/badge/architecture-Multi--Agent-orange.svg)](#architecture)

## 🚀 核心架构演进

> **Pipeline 是骨架，Agent 是肌肉，人类是大脑**

当前版本实现了一个**通用的、API 驱动的开源 Go 后端研发助手**。
代码已经具备以下主干能力：
- 支持 `Anthropic`、`OpenAI` 和 `Qwen/DashScope` 三种 LLM Provider。
- 通过四阶段 Agent Prompt 驱动需求设计、编码、测试和审查。
- 通过飞书交互卡片挂起审批，再由带签名校验与事件幂等的 Webhook 恢复流程。
- 能把设计规范拆分为 `rules/` 和 `skills/`，让编码 Agent 按需读取。
- 在流程结束后，默认尝试对 `demo-app/` 执行 Docker 构建和启动。

### 1. 整体流转架构

```mermaid
graph TD
    subgraph 飞书生态
        A[多维表格: 录入新需求] --> B
        H[消息卡片: 人类大脑审批] -.->|点击同意/驳回| I(唤醒 Pipeline)
    end

    subgraph lfe["LarkFlow 核心引擎 (Python Pipeline)"]
        B[Pipeline启动: 接收需求] --> C{阶段1: Design}
        C -->|注入 phase1_design.md| D[架构师 Agent]
        D -.->|调用| T1[inspect_db: 查询表结构]
        D -->|调用 ask_human_approval| E((挂起等待))
        E -.->|Webhook 触发| H
        I --> F{阶段2: Coding}
        F -->|注入 phase2_coding.md| J[高级开发 Agent]
        J -.->|主动查阅| R[rules/ & skills/ 知识库]
        J -.->|调用| T2[file_editor: 读写项目代码]
        J --> L{阶段3: Test}
        L -->|注入 phase3_test.md| M[测试 Agent]
        M -.->|调用| T3[run_bash: go test ./...]
        M --> O{阶段4: Review}
        O -->|注入 phase4_review.md| P[代码审查 Agent]
        P --> N[流转完成: 准备部署]
    end
```

### 2. 目录结构

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
│   │   ├── tools_runtime.py
│   │   ├── tools_schema.py
│   │   └── utils/lark_doc.py
│   ├── rules/
│   │   ├── flow-rule.md
│   │   ├── skill-routing.yaml      # 路由唯一真源
│   │   ├── skill-routing.md        # 人类可读镜像
│   │   └── skill-feedback-loop.md  # Review → Skills 回灌闭环
│   ├── scripts/
│   │   └── gen_tools_doc.py
│   ├── skills/                     # 按关注点分层的 md 知识库
│   │   ├── lang/                   # concurrency / error / python-comments
│   │   ├── transport/              # http / pagination
│   │   ├── infra/                  # database / redis / config
│   │   ├── governance/             # auth / rate_limit / idempotency / logging
│   │   └── domain/                 # order / user / payment
│   ├── templates/
│   │   └── kratos-skeleton/        # Kratos 精简骨架：每次需求启动时 copy 到 demo-app/
│   └── tests/
│       └── prompts/                # Prompt 评测集
│           ├── fixtures/*.yaml     # 5 个 fixture
│           └── eval.py
├── demo-app/                  # 目标产物目录；当前仓库未默认提交该目录
└── image/
```

## LarkFlow 引擎结构

### 1. Agents

`LarkFlow/agents/` 里定义了四个阶段的 System Prompt：

- `phase1_design.md`：系统设计与审批前方案输出。
- `phase2_coding.md`：按 `rules/` 和 `skills/` 实现 Go 代码。
- `phase3_test.md`：补测试并运行验证。
- `phase4_review.md`：从规范角度复查并修正问题。

### 2. Rules 和 Skills

这部分是编码 Agent 的"检索式规范库"：

- `rules/flow-rule.md`：总规则，要求先查路由表再编码。
- `rules/skill-routing.yaml`：**路由表唯一真源**，结构为 `keywords / skill / weight` 列表，业务 skill 默认 `weight=1.2` 优先于横切 1.0；Phase 2 Agent 按权重取 Top 5 读取。`rules/skill-routing.md` 作为人类可读镜像并在顶部声明以 YAML 为准。
- `rules/skill-feedback-loop.md`：Phase 4 Reviewer 输出 `<skill-feedback>` 块 → 周度 triage → PR 回灌 `skills/*.md` 的四步闭环。
- `skills/**/*.md`：按 `lang/`、`transport/`、`infra/`、`governance/`、`domain/` 五层组织的 md 知识库，覆盖并发/错误、HTTP/分页、DB/Redis/Config、认证/限流/幂等/日志，以及订单/用户/支付三类业务规范。每份 md 保持 🔴 CRITICAL / 🟡 HIGH 分级 + Go ❌/✅ 代码对照结构。

### 3. Pipeline

`LarkFlow/pipeline/engine.py` 负责主状态机和工具执行：

- 通过 `start_new_demand()` 启动一个新需求。
- 在设计阶段调用 `ask_human_approval` 后挂起。
- 收到审批回调后，进入 Coding、Test、Review 阶段。
- 最后默认对仓库根下的 `demo-app/` 尝试构建 Docker 镜像并运行。

`LarkFlow/pipeline/llm_adapter.py` 统一了三类模型调用：

- `Anthropic Messages API`
- `OpenAI Responses API`
- `Qwen/DashScope OpenAI-compatible Chat Completions API`

`LarkFlow/pipeline/lark_interaction.py` 提供 FastAPI Webhook 服务，负责：

- 校验飞书回调 token、签名与加密载荷
- 接收飞书卡片按钮点击
- 接收“开始执行”这类 HTTP 触发
- 读取飞书文档链接内容
- 唤醒已挂起的 Pipeline

`LarkFlow/pipeline/lark_client.py` 负责统一构建和发送飞书卡片/文本消息。

## 快速开始

### 1. 环境准备

确保你已经安装了 Python 3.9+，并配置了可用的 LLM API Key（Anthropic、OpenAI 或 Qwen/DashScope）。

```bash
# 克隆仓库
git clone https://github.com/your-repo/larkflow.git
cd LarkFlow/LarkFlow

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

在 `LarkFlow/` 目录下创建 `.env` 文件（可参考 `.env.example`）：

```env
LLM_PROVIDER=anthropic

# Database
DATABASE_URL=sqlite:///demo-app/app.db
# DATABASE_URL=mysql://root:password@127.0.0.1:3306/larkflow_demo
# DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/larkflow_demo

# 飞书应用机器人 (Bot API)
LARK_APP_ID=cli_xxx
LARK_APP_SECRET=xxx
LARK_CHAT_ID=ou_xxx
LARK_RECEIVE_ID_TYPE=open_id
LARK_VERIFICATION_TOKEN=verify_xxx
LARK_ENCRYPT_KEY=encrypt_xxx

# Claude / Anthropic
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_BASE_URL=
ANTHROPIC_MODEL=claude-sonnet-4-6

# Codex / OpenAI
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-codex
OPENAI_REASONING_EFFORT=medium
OPENAI_MAX_RETRIES=3
OPENAI_RETRY_BASE_SECONDS=5
OPENAI_RETRY_MAX_SECONDS=60

# Qwen / DashScope
QWEN_API_KEY=sk-...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.6-plus
# 也兼容 DASHSCOPE_API_KEY / DASHSCOPE_BASE_URL / DASHSCOPE_MODEL
```

- 当 `LLM_PROVIDER=anthropic` 时，Pipeline 使用 Claude / Anthropic SDK。
- 当 `LLM_PROVIDER=openai` 时，Pipeline 使用 OpenAI Responses API。
- 当 `LLM_PROVIDER=qwen` 时，Pipeline 使用 OpenAI SDK 连接 DashScope 的 OpenAI-compatible Chat Completions API；优先读取 `QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`，同时兼容 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`。
- `inspect_db` 依赖 `DATABASE_URL` 读取真实数据库 schema，目前支持 SQLite 和 MySQL，只允许只读查询。
- 若要执行真实 MySQL 集成测试，可额外设置 `MYSQL_TEST_DATABASE_URL`，然后运行 `python -m unittest tests.test_inspect_db_mysql_integration`。
- `agents/tools_definition.md` 由 `pipeline/tools_schema.py` 单源生成；修改工具协议后执行 `python scripts/gen_tools_doc.py`，校验一致性可执行 `python scripts/gen_tools_doc.py --check`。
- 飞书回调入口支持 `LARK_VERIFICATION_TOKEN` 与 `LARK_ENCRYPT_KEY` 校验；同一个 `header.event_id` 在 24 小时内只会触发一次 pipeline 恢复。
- LLM 适配层会在 `AgentTurn.usage` 中统一输出 `prompt_tokens`、`completion_tokens`、`total_tokens`、`latency_ms`；OpenAI 调用支持 `OPENAI_MAX_RETRIES`、`OPENAI_RETRY_BASE_SECONDS`、`OPENAI_RETRY_MAX_SECONDS` 控制重试，Qwen 走 Chat Completions 的工具调用格式。

### 3. 运行

启动 FastAPI 服务来接收真实的飞书 Webhook：

```bash
uvicorn pipeline.lark_interaction:app --host 0.0.0.0 --port 8000
```

也可以通过 Docker 构建并启动服务：

```bash
docker build -t larkflow LarkFlow/
docker run --rm -p 8000:8000 larkflow
```

如果构建时拉取 `python:3.11-slim` 超时，可先执行 `docker pull python:3.11-slim`，或检查 Docker Desktop 代理/网络配置。

飞书webhook可以使用ngrok隧道地址；

配置飞书机器人（事件和回调），并开通相关权限（表格，消息等）；

通过飞书表格即可启动需求：

![image-20260418163029819](./image/image.png)

### 4.简单测试

简单测试：你可以直接运行引擎脚本来模拟一个需求的完整生命周期：（不会向飞书发送技术方案卡片）

```bash
python pipeline/engine.py
```

---

## 核心特性：按需检索 (RAG) 知识库

LarkFlow 的知识库架构会让 AI 在写代码前强制读取 `rules/skill-routing.yaml` 路由表，按关键词匹配并按 `weight` 降序取 Top 5 skill。

例如，当需求包含"Redis 缓存"时，AI 会自动调用 `file_editor` 工具读取 `skills/infra/redis.md`，学习团队规定的 Pipeline 批量操作和过期时间规范，从而写出完全符合团队标准的代码。这极大地降低了 Token 消耗并消除了 AI 幻觉。

路由命中质量由 `tests/prompts/` 下的评测集保证：5 个 fixture 覆盖 CRUD / Redis 缓存 / 分页列表 / 幂等支付回调 / 并发批任务，断言每个需求应触发的工具、应读取的 skill 以及代码产物的正则黑白名单。CI 友好的 mock 模式可用：

```bash
python tests/prompts/eval.py --mock      # 全量跑
python tests/prompts/eval.py --only redis_cache_product_detail
```

---

## 当前能力边界

按当前代码状态，以下边界仍然存在：

- `inspect_db` 目前仅支持 SQLite 和 MySQL；若后续引入其他数据库引擎，还需要继续补适配。
- 默认部署目标仍是仓库根下的 `demo-app/`；如果本地没有该目录，需要先准备目标产物目录或在 session 中显式设置 `target_dir`。

## 相关文档

- `LarkFlow/LarkFlow.md`：引擎模块速览。
- `LarkFlow/CHANGELOG.md`：版本变更记录。

## 🔮 未来展望

本框架具备极强的可扩展性与业务适应能力：
- **规范无缝迁移**：未来可轻松接入并适配各公司内部的专属中间件规范与代码风格指南。
- **基建深度打通**：支持通过内部 MCP (Model Context Protocol) 协议，直连生产/测试环境的数据库、缓存及配置中心。
- **CI/CD 自动化闭环**：可直接对接自动化部署流水线，实现测试环境的一键部署，并将详尽的自动化测试报告与运行效果实时回传至飞书卡片。
- **加入业务规则代码**：轻松加入业务规则代码，更加简单的写业务
