# LarkFlow Framework

LarkFlow 已经从一个依赖本地 IDE 插件的工具，进化为一个**完全无头（Headless）、基于多智能体（Multi-Agent）协作的自动化研发工作流引擎**。

[![Version](https://img.shields.io/badge/version-1.4.4-blue.svg)](https://github.com/your-repo/larkflow)
[![Architecture](https://img.shields.io/badge/architecture-Multi--Agent-orange.svg)](#architecture)
[![Scaffold](https://img.shields.io/badge/scaffold-Kratos%20v2.7-00ADD8.svg)](#kratos-骨架自动物化)

## 🚀 核心架构演进

> **Pipeline 是骨架，Agent 是肌肉，人类是大脑**

当前版本实现了一个**通用的、API 驱动的 Kratos 微服务研发助手**。
代码已经具备以下主干能力：
- 支持 `Anthropic`、`OpenAI` 和 `Qwen/DashScope` 三种 LLM Provider。
- 通过四阶段 Agent Prompt 驱动需求设计、编码、测试和审查。
- 通过飞书交互卡片挂起审批，再由带签名校验与事件幂等的 Webhook 恢复流程。
- 知识库按关注点分层（`lang/ transport/ infra/ governance/ domain/ framework/`），Agent 按关键词权重命中并按需读取。
- **每个新需求启动时自动把 `templates/kratos-skeleton/` 物化到 `demo-app/`**，Agent 按 Kratos v2.7 的四层布局（`api/biz/data/service/server`）补业务代码。
- 在流程结束后，默认对 `demo-app/` 执行 Docker 多阶段构建（`golang:1.22-alpine` builder + `alpine:3.19` runtime）并启动容器。

### 1. 整体流转架构

```mermaid
graph TD
    subgraph feishu["飞书生态"]
        A[多维表格: 录入新需求] --> B
        H[消息卡片: 人类大脑审批] -.->|点击同意/驳回| I(唤醒 Pipeline)
    end

    subgraph lfe["LarkFlow 核心引擎 (Python Pipeline)"]
        B[Pipeline 启动: 接收需求] --> SC{{Scaffold 钩子}}
        SC -->|templates/kratos-skeleton<br/>copytree 到 demo-app/| C{阶段1: Design}
        C -->|注入 phase1_design.md| D[架构师 Agent]
        D -.->|inspect_db| T1[查询真实表结构]
        D -.->|设计必填 Kratos Layering 表| KL[api/biz/data/service/server/wire]
        D -->|ask_human_approval| E((挂起等待))
        E -.->|Webhook 触发| H
        I --> F{阶段2: Coding}
        F -->|注入 phase2_coding.md| J[高级开发 Agent]
        J -.->|skill 路由 Top5<br/>defaults 必读 kratos.md| R["rules/ + skills/**/*.md<br/>（framework 1.3 / domain 1.2 / 其他 1.0）"]
        J -.->|5 步流程: proto → make api → biz → data → service → wire| T2["file_editor 写<br/>demo-app/{api,internal/*}"]
        J --> L{阶段3: Test}
        L -->|注入 phase3_test.md| M[测试 Agent]
        M -.->|run_bash| T3["cd demo-app && make api && make wire && go test ./..."]
        M --> O{阶段4: Review}
        O -->|注入 phase4_review.md| P[代码审查 Agent]
        P -.->|🔴 跨层违规 / codegen 不同步 直接 block| RL[阻断]
        P --> N[流转完成: 准备部署]
        N --> DP[docker build demo-app<br/>两阶段: golang:1.22 → alpine]
    end
```

> 虚线为数据流（工具调用、知识查阅、规则比对），实线为状态流转。Scaffold 钩子在 `start_new_demand` 起点自动执行，后续 resume 幂等跳过。

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
│   │   ├── framework/              # kratos (weight 1.3, defaults)
│   │   ├── lang/                   # concurrency / error / python-comments
│   │   ├── transport/              # http / pagination
│   │   ├── infra/                  # database / redis / config
│   │   ├── governance/             # auth / rate_limit / idempotency / logging
│   │   └── domain/                 # order / user / payment (weight 1.2)
│   ├── templates/
│   │   └── kratos-skeleton/        # Kratos v2.7 精简骨架，每次需求启动时 copytree 到 demo-app/
│   │       ├── api/                # domain proto (Agent 填入)
│   │       ├── cmd/server/         # main.go + wire.go
│   │       ├── configs/            # HTTP 8080 + gRPC 9000
│   │       ├── internal/{biz,conf,data,server,service}/
│   │       ├── third_party/google/api/
│   │       ├── Makefile            # init / api / wire / build / test / run
│   │       └── Dockerfile          # 两阶段 golang:1.22-alpine → alpine:3.19
│   └── tests/
│       ├── prompts/                # Prompt 评测集
│       │   ├── fixtures/*.yaml     # 6 个 fixture（含 grpc_order_service）
│       │   └── eval.py
│       └── test_engine_scaffold.py # scaffold 钩子单测
├── demo-app/                  # 产物目录；.gitignore 排除，每次需求由 engine 自动物化
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

- `rules/flow-rule.md`：总规则，要求先查路由表再编码；明确"产物是 Kratos 骨架，禁止平铺 .go 文件"。
- `rules/skill-routing.yaml`：**路由表唯一真源**，结构为 `keywords / skill / weight` 列表。权重分三档——**framework `1.3`（架构级硬约束）> domain `1.2`（业务） > 其他 `1.0`**。Phase 2 Agent 按权重取 Top 5 读取；`defaults` 头条 `skills/framework/kratos.md` 保证每次必读。`rules/skill-routing.md` 作为人类可读镜像并在顶部声明以 YAML 为准。
- `rules/skill-feedback-loop.md`：Phase 4 Reviewer 输出 `<skill-feedback>` 块 → 周度 triage → PR 回灌 `skills/*.md` 的四步闭环。
- `skills/**/*.md`：按 `framework/ / lang/ / transport/ / infra/ / governance/ / domain/` 六层组织的知识库，覆盖 Kratos 分层/wire/make 工具链、并发/错误、HTTP/分页、DB/Redis/Config、认证/限流/幂等/日志，以及订单/用户/支付业务规范。每份 md 保持 🔴 CRITICAL / 🟡 HIGH / 🟢 最佳实践 分级 + Go ❌/✅ 代码对照结构。

### 3. Pipeline

`LarkFlow/pipeline/engine.py` 负责主状态机和工具执行：

- 通过 `start_new_demand()` 启动新需求；起点调用 **`_ensure_target_scaffold()`** 把 `templates/kratos-skeleton/` 物化到 `demo-app/`（空目录物化、已物化幂等、脏状态拒绝、模板缺失报错四种情况都在 `tests/test_engine_scaffold.py` 中覆盖）。
- 在设计阶段调用 `ask_human_approval` 后挂起；pipeline 服务重启后 resume 老需求时，scaffold 钩子幂等跳过，Agent 看到的是上次留下的代码。
- 收到审批回调后，按显式状态机 `design → coding → testing → reviewing → deploying → done` 推进；任一阶段 LLM 异常 / 超时 / 超轮数 / 连续空响应都会落入 `failed` 并发飞书告警。
- 最后委托 `pipeline/deploy_strategy.py` 的 `DeployStrategy` 完成 Docker 构建与运行；`target_dir` 与策略名从 session 读取，未指定时默认 `demo-app/` + `docker-go` 策略。

引擎可靠性组件（release/A 生产化改造，对应 `ownership.pdf` 中的 A1~A6）：

- `LarkFlow/pipeline/persistence.py` 的 `SqliteSessionStore` 把 session 持久化到 `.larkflow/sessions.db`（WAL + 线程锁），进程重启后通过 `list_active()` 列出未完成需求并自动续跑；序列化时自动剥离 `client` / `logger` 等 transient 字段，载入时按 provider 重建。
- `resume_from_phase(demand_id, phase)` 入口支持从 `coding / testing / reviewing / deploying` 任意阶段断点续跑，失败不退回 Phase 1。
- `run_agent_loop` 叠加 `AGENT_TURN_TIMEOUT` 单轮超时、`AGENT_MAX_RETRIES` 指数退避、`AGENT_MAX_TURNS` 最大轮数、`AGENT_MAX_EMPTY_STREAK` 空响应退出四道保护，与 `llm_adapter.py` 中 SDK 层重试解耦。
- `LarkFlow/pipeline/observability.py` 给每个需求发结构化 JSON 日志（stdout + `logs/larkflow.jsonl`），读 `AgentTurn.usage` 累加到 `session["metrics"]`，可用 `jq` 按 `demand_id` 聚合 token 与延迟。

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
- **引擎可靠性相关环境变量**（均有合理默认值，按需覆盖）：
  - `LARKFLOW_SESSION_DB`：会话持久化 SQLite 路径，默认 `.larkflow/sessions.db`（已在 `.gitignore` 中忽略）。
  - `LARKFLOW_LOG_FILE`：结构化日志文件路径，默认 `logs/larkflow.jsonl`。
  - `LARKFLOW_LOG_LEVEL`：默认 `INFO`。
  - `AGENT_TURN_TIMEOUT`：单轮 LLM 调用超时（秒），默认 `120`。
  - `AGENT_MAX_RETRIES`：单轮 LLM 调用的指数退避重试次数，默认 `3`。
  - `AGENT_MAX_TURNS`：单阶段最大轮数，超过置 `failed` 并告警，默认 `30`。
  - `AGENT_MAX_EMPTY_STREAK`：连续空响应阈值，超过置 `failed`，默认 `3`。

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

路由命中质量由 `tests/prompts/` 下的评测集保证：6 个 fixture 覆盖 CRUD / Redis 缓存 / 分页列表 / 幂等支付回调 / 并发批任务 / gRPC 订单服务，断言每个需求应触发的工具、应读取的 skill（含 `skills/framework/kratos.md`）以及代码产物的正则黑白名单。CI 友好的 mock 模式可用：

```bash
python tests/prompts/eval.py --mock      # 全量跑
python tests/prompts/eval.py --only grpc_order_service
```

---

## Kratos 骨架自动物化

从 v1.4.1 起，所有生成到 `demo-app/` 的 Go 代码都遵守 Kratos v2.7 四层布局。每次新需求触发时，engine 会把仓库里只读的 `LarkFlow/templates/kratos-skeleton/` 整个 `copytree` 到 `demo-app/`，Agent 从完整骨架起步、按五步流程补业务代码。

### 分层职责

| 层 | 路径 | 允许依赖 | 禁止依赖 |
|---|---|---|---|
| `api/<domain>/v1/` | `*.proto` | google.api.http 注解 | — |
| `internal/service` | 对接 proto handler | `internal/biz` | `gorm` / `redis` / `internal/data` |
| `internal/biz` | 领域层 usecase + Repo 接口 | 自身定义的 Repo interface | HTTP/gRPC 原语 / `internal/data` 具体类型 |
| `internal/data` | Repo 实现（gorm / redis） | DB 驱动 | `internal/biz` / `internal/service` |
| `internal/server` | HTTP + gRPC server 注册 | 注册 proto service | 直接访问 biz / data |
| `cmd/server/wire.go` | wire DI 汇聚 | 激活四层 ProviderSet | — |

### 新增一个 domain（5 步）

```
1. api/order/v1/order.proto              # service Order { rpc CreateOrder ... } + google.api.http
   run_bash: cd demo-app && make api     # 生成 *.pb.go / *_grpc.pb.go / *_http.pb.go
2. internal/biz/order.go                 # OrderUsecase + OrderRepo 接口 + NewOrderUsecase → biz.ProviderSet
3. internal/data/order.go                # orderRepo 实现 biz.OrderRepo + NewOrderRepo → data.ProviderSet
4. internal/service/order.go             # OrderService → service.ProviderSet；在 server 里注册
5. cmd/server/wire.go                    # 取消 biz/data/service.ProviderSet 的注释
   run_bash: cd demo-app && make wire    # 重新生成 wire_gen.go
```

完整规范：`skills/framework/kratos.md`（路由表 `weight: 1.3`，`defaults` 头条，每次需求 Phase 2 都会读）。

### 本地验证骨架

```bash
docker build LarkFlow/templates/kratos-skeleton/          # 21 步构建全通过
docker run --rm -p 8080:8080 -p 9000:9000 <image-id>     # HTTP 8080 + gRPC 9000
```

---

## 当前能力边界

按当前代码状态，以下边界仍然存在：

- `inspect_db` 目前仅支持 SQLite 和 MySQL；若后续引入其他数据库引擎，还需要继续补适配。
- Kratos 骨架要求宿主 Go ≥ 1.22（否则 `make init` / `make api` 在本地跑不通；Docker builder 使用 `golang:1.22-alpine` 不受影响）。
- `SqliteSessionStore` 默认走本地文件系统，多实例部署时应把 `.larkflow/sessions.db` 放在共享卷，或换成 Redis 实现（`SessionStore` 抽象已预留）。
- `AGENT_TURN_TIMEOUT` 基于 `ThreadPoolExecutor.result(timeout=...)`，只能让**等待**超时、不能真正杀掉正在跑的 LLM 调用线程；强杀需要切换到 `signal.alarm` 或子进程沙箱。当前方案叠加 SDK 自带的 connect/read timeout 已能覆盖生产场景。
- `DeployStrategy` 当前只有 `DockerfileGoStrategy` 一个内置实现；非 Docker / 非 Go 的部署目标需通过 `register(strategy)` 自行注入。

## 相关文档

- `LarkFlow/LarkFlow.md`：引擎模块速览。
- `LarkFlow/CHANGELOG.md`：版本变更记录。

## 🔮 未来展望

本框架具备极强的可扩展性与业务适应能力：
- **规范无缝迁移**：未来可轻松接入并适配各公司内部的专属中间件规范与代码风格指南。
- **基建深度打通**：支持通过内部 MCP (Model Context Protocol) 协议，直连生产/测试环境的数据库、缓存及配置中心。
- **CI/CD 自动化闭环**：可直接对接自动化部署流水线，实现测试环境的一键部署，并将详尽的自动化测试报告与运行效果实时回传至飞书卡片。
- **加入业务规则代码**：轻松加入业务规则代码，更加简单的写业务
