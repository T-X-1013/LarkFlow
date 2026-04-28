# LarkFlow Framework

LarkFlow 已经从一个依赖本地 IDE 插件的工具，进化为一个**完全无头（Headless）、基于多阶段多 Agent（串行）自动化研发工作流引擎**。

[![Version](https://img.shields.io/badge/version-1.6.0-blue.svg)](https://github.com/your-repo/larkflow)
[![Architecture](https://img.shields.io/badge/architecture-Multi--Agent-orange.svg)](#architecture)
[![Scaffold](https://img.shields.io/badge/scaffold-Kratos%20v2.7-00ADD8.svg)](#kratos-骨架自动物化)

## 🚀 核心架构演进

> **Pipeline 是骨架，Agent 是肌肉，人类是大脑**

当前版本实现了一个**通用的、API 驱动的 Kratos 微服务研发助手**。
代码已经具备以下主干能力：
- 支持 `Anthropic`、`OpenAI`、`Qwen/DashScope` 和 `Doubao/Ark` 四种 LLM Provider。
- 通过四阶段 Agent Prompt 驱动需求设计、编码、测试和审查。
- 通过飞书交互卡片挂起审批，再由 `lark-oapi` SDK 的 WebSocket 长连通道收取卡片点击事件、配合 24 小时 event_id 幂等恢复流程（不再需要公网可达的 Webhook）。
- 知识库按关注点分层（`lang/ transport/ infra/ governance/ domain/ framework/`），Agent 按关键词权重命中并按需读取。
- **每个新需求启动时自动把 `templates/kratos-skeleton/` 物化到 `demo-app/`**，Agent 按 Kratos v2.7 的四层布局（`api/biz/data/service/server`）补业务代码。
- 在流程结束后，默认对 `demo-app/` 执行 Docker 多阶段构建（`golang:1.22-alpine` builder + `alpine:3.19` runtime）并启动容器。

### 1. 整体流转架构

```mermaid
graph TD
    subgraph feishu["飞书生态"]
        A[多维表格: 新增/编辑需求行]
        H[启动卡片: 开始处理 / 驳回]
        Q[审批卡片: 同意 / 驳回设计]
        DOC[飞书文档: 技术方案 docx]
    end

    subgraph lfe["LarkFlow 核心引擎 (Python Pipeline)"]
        WS["lark_interaction.py<br/>WebSocket 长连 + EventDispatcher"]
        BL["lark_bitable_listener.py<br/>订阅 Base 事件 / 读取记录 / 发启动卡 / 回写状态"]
        SC{{_ensure_target_scaffold()}}
        D1{阶段1: Design}
        D2{阶段2: Coding}
        D3{阶段3: Test}
        D4{阶段4: Review}
        DP[阶段5: Deploying]

        A -->|drive.file.bitable_record_changed_v1| WS
        WS --> BL
        BL -->|send_demand_start_card| H
        H -.->|start_demand / reject_demand| WS
        WS -->|handle_start_request| SC
        SC -->|templates/kratos-skeleton<br/>copytree 到 demo-app/| D1

        D1 -->|phase1_design.md| AG1[架构师 Agent]
        AG1 -.->|inspect_db| DB[查询真实表结构]
        AG1 -.->|rules + skills 路由| KB["rules/ + skills/**/*.md"]
        AG1 -->|ask_human_approval| TD["_prepare_tech_doc()<br/>create_tech_doc + grant_doc_access<br/>回写 Base 技术方案文档列"]
        TD --> DOC
        TD --> Q
        Q -.->|approve / reject| WS
        WS -->|resume_after_approval| D2

        D2 -->|phase2_coding.md| AG2[高级开发 Agent]
        AG2 -.->|file_editor / run_bash| GEN["demo-app/{api,internal/*}<br/>proto → make api → biz → data → service → wire"]
        D2 --> D3

        D3 -->|phase3_test.md| AG3[测试 Agent]
        AG3 -.->|check_kratos_contract.py<br/>make api / wire / build / go test| TEST[契约校验 + 构建测试]
        D3 --> D4

        D4 -->|phase4_review.md| AG4[代码审查 Agent]
        AG4 -.->|Review 发现问题继续修复| GEN
        D4 --> DP

        DP -->|deploy_strategy.py| DOCKER["docker build / docker run<br/>demo-app-container"]
    end

    subgraph obs["可观测性"]
        OTEL["telemetry/{otel.py,hooks.py}<br/>LarkFlow spans"]
        COL[otel-collector]
        TEMPO[Tempo]
        LOKI[Loki]
        GRAF[Grafana]
        PROMTAIL[promtail]
    end

    WS -.-> OTEL
    D1 -.-> OTEL
    D2 -.-> OTEL
    D3 -.-> OTEL
    D4 -.-> OTEL
    DP -.-> OTEL
    OTEL --> COL --> TEMPO --> GRAF
    BL -.->|"logs/larkflow.jsonl / logs/*.log"| PROMTAIL --> LOKI --> GRAF
    DOCKER -.->|容器 stdout| PROMTAIL
```

> 实线表示主状态流转，虚线表示工具调用、知识检索、日志/trace 数据流。`start_new_demand()` 会先物化 `templates/kratos-skeleton/` 到 `demo-app/`，后续 resume 流程直接复用已有产物目录，不重复覆盖。

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
│   │   ├── deploy_strategy.py
│   │   ├── persistence.py
│   │   ├── observability.py
│   │   ├── lark_client.py
│   │   ├── lark_doc_client.py
│   │   ├── lark_interaction.py
│   │   ├── lark_bitable_listener.py  # Base 记录事件 → 发启动卡 / 回写状态
│   │   ├── llm_adapter.py
│   │   ├── tools_runtime.py
│   │   ├── tools_schema.py
│   │   ├── otel.py                   # 兼容薄壳，转发到 telemetry/
│   │   ├── otel_hooks.py             # 兼容薄壳，转发到 telemetry/
│   │   └── utils/
│   │       ├── lark_doc.py           # 读取飞书文档正文
│   │       └── lark_sdk.py           # 单例 lark-oapi Client 工厂
│   ├── telemetry/
│   │   ├── otel.py                   # OTLP 初始化 / no-op fallback
│   │   └── hooks.py                  # 业务埋点 hook 封装
│   ├── rules/
│   │   ├── flow-rule.md
│   │   ├── skill-routing.yaml      # 路由唯一真源
│   │   ├── skill-routing.md        # 人类可读镜像
│   │   └── skill-feedback-loop.md  # Review → Skills 回灌闭环
│   ├── scripts/
│   │   ├── check_kratos_contract.py
│   │   ├── gen_tools_doc.py
│   │   ├── gen_skill_routing_md.py  # 由 skill-routing.yaml 生成 .md 镜像
│   │   └── smoke_lark_sdk.py
│   ├── skills/                     # 按关注点分层的 md 知识库
│   │   ├── framework/              # kratos (weight 1.3, defaults)
│   │   ├── lang/                   # concurrency / error / python-comments
│   │   ├── transport/              # http / rpc / pagination / mq
│   │   ├── infra/                  # database / redis / config
│   │   ├── governance/             # auth / rate_limit / idempotency / logging
│   │   └── domain/                 # order / user / payment (weight 1.2)
│   ├── templates/
│   │   └── kratos-skeleton/        # Kratos v2.7 精简骨架，每次需求启动时 copytree 到 demo-app/
│   │       ├── api/                # 业务 proto 入口（空骨架默认 .gitkeep）
│   │       ├── cmd/server/         # main.go / otel.go / wire.go
│   │       ├── configs/            # HTTP 8080 + gRPC 9000
│   │       ├── internal/{biz,conf,data,server,service}/
│   │       ├── otel/               # 本地 Tempo/Loki/Grafana/Prometheus/promtail 编排
│   │       ├── third_party/validate/
│   │       ├── Makefile            # init / api / wire / build / test / run
│   │       └── Dockerfile          # 两阶段 golang:1.22-alpine → alpine:3.19
│   └── tests/
│       ├── unit/
│       │   ├── engine/             # scaffold / state machine / observability / approval tech doc
│       │   ├── deploy/
│       │   ├── tools/
│       │   ├── llm/
│       │   └── lark/
│       ├── integration/
│       │   ├── engine/
│       │   └── external/
│       ├── prompts/                # Prompt 评测集
│       │   ├── fixtures/*.yaml
│       │   └── eval.py
│       ├── test_check_kratos_contract.py
│       └── test_kratos_scaffold_contract.py
├── demo-app/                       # 产物目录；.gitignore 排除，每次需求由 engine 自动物化
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
- `skills/**/*.md`：按 `framework/ / lang/ / transport/ / infra/ / governance/ / domain/` 六层组织的知识库，覆盖 Kratos 分层/wire/make 工具链、并发/错误、HTTP/RPC/分页/消息队列、DB/Redis/Config、认证/限流/幂等/日志/韧性/可观测/服务发现，以及订单/用户/支付业务规范。每份 md 保持 🔴 CRITICAL / 🟡 HIGH / 🟢 最佳实践 分级 + Go ❌/✅ 代码对照结构。

### 3. Pipeline

`LarkFlow/pipeline/engine.py` 负责主状态机和工具执行：

- 通过 `start_new_demand()` 启动新需求；起点调用 **`_ensure_target_scaffold()`** 把 `templates/kratos-skeleton/` 物化到 `demo-app/`（空目录物化、已物化幂等、脏状态拒绝、模板缺失报错四种情况都在 `tests/unit/engine/test_engine_scaffold.py` 中覆盖）。
- 在设计阶段调用 `ask_human_approval` 后挂起；pipeline 服务重启后 resume 老需求时，scaffold 钩子幂等跳过，Agent 看到的是上次留下的代码。
- 收到审批回调后，按显式状态机 `design → design_pending → coding → testing → reviewing → deploying → done` 推进；任一阶段 LLM 异常 / 超时 / 超轮数 / 连续空响应都会落入 `failed` 并发飞书告警。
- 最后委托 `pipeline/deploy_strategy.py` 的 `DeployStrategy` 完成 Docker 构建与运行；`target_dir` 与策略名从 session 读取，未指定时默认 `demo-app/` + `docker-go` 策略。

引擎可靠性组件（release/A 生产化改造，对应 `ownership.pdf` 中的 A1~A6）：

- `LarkFlow/pipeline/persistence.py` 的 `SqliteSessionStore` 把 session 持久化到 `.larkflow/sessions.db`（WAL + 线程锁），进程重启后通过 `list_active()` 列出未完成需求并自动续跑；序列化时自动剥离 `client` / `logger` 等 transient 字段，载入时按 provider 重建。
- `resume_from_phase(demand_id, phase)` 入口支持从 `coding / testing / reviewing / deploying` 任意阶段断点续跑，失败不退回 Phase 1。
- `run_agent_loop` 叠加 `AGENT_TURN_TIMEOUT` 单轮超时、`AGENT_MAX_RETRIES` 指数退避、`AGENT_MAX_TURNS` 最大轮数、`AGENT_MAX_EMPTY_STREAK` 空响应退出四道保护，与 `llm_adapter.py` 中 SDK 层重试解耦。
- `LarkFlow/pipeline/observability.py` 给每个需求发结构化 JSON 日志（stdout + `logs/larkflow.jsonl`），读 `AgentTurn.usage` 累加到 `session["metrics"]`，可用 `jq` 按 `demand_id` 聚合 token 与延迟。

`LarkFlow/pipeline/llm_adapter.py` 统一了四类模型调用：

- `Anthropic Messages API`
- `OpenAI Responses API`
- `Qwen/DashScope OpenAI-compatible Chat Completions API`
-  `doubao 1.6/2.0pro`

`LarkFlow/pipeline/lark_interaction.py` 基于 `lark-oapi` SDK 提供事件监听器，负责：

- 通过 `lark_oapi.ws.Client` 与飞书建立 WebSocket 长连，由 SDK 兜底 URL 校验、verification token、签名与加密
- 通过 `EventDispatcherHandler.register_p2_card_action_trigger` 订阅卡片按钮点击
- 通过 `register_p2_drive_file_bitable_record_changed_v1` 订阅多维表格记录变更，作为新需求的入向触发（替代旧的 HTTP webhook 方案）
- 维护 24 小时 `event_id` 幂等 SQLite（`LARK_EVENT_STORE_PATH`），避免重复点击二次触发 pipeline
- 唤醒已挂起的 Pipeline（approve → 进入 coding，reject → 回 design）

`LarkFlow/pipeline/lark_bitable_listener.py` 负责进程启动时向飞书订阅需求 Base 的文件事件，并在新增/编辑记录到达时向审批群发送「需求启动」卡片；状态列回写（`待启动 → 已发卡 → 处理中 → 已启动 / 驳回 / 失败`）作为幂等去重标记。

`LarkFlow/pipeline/lark_client.py` 通过 `client.im.v1.message.create` 统一发送飞书卡片/文本消息；`LarkFlow/pipeline/utils/lark_sdk.py` 作为共享的 `lark-oapi` Client 工厂，让出站消息、文档读取、入站事件共用一份 token 缓存；`LarkFlow/pipeline/utils/lark_doc.py` 通过 `client.wiki.v2.space.get_node` 与 `client.docx.v1.document.raw_content` 读取飞书云文档。

## 快速开始

### 1. 环境准备

确保你已经安装了 Python 3.11+，并配置了可用的 LLM API Key（Anthropic、OpenAI、Qwen/DashScope 或 Doubao/Ark）。

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

# 飞书应用机器人 (lark-oapi SDK, WebSocket 长连模式)
LARK_APP_ID=cli_xxx
LARK_APP_SECRET=xxx
LARK_CHAT_ID=ou_xxx
LARK_RECEIVE_ID_TYPE=open_id
# 可选：SDK 日志级别 DEBUG/INFO/WARNING/ERROR，默认 INFO
# LARK_LOG_LEVEL=INFO
# 可选：飞书事件幂等 SQLite 路径，默认 tmp/lark_event_store.db
# LARK_EVENT_STORE_PATH=

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

# Doubao / Ark
DOUBAO_API_KEY=ark-...
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=ep-...
# 也兼容 ARK_API_KEY / ARK_BASE_URL / ARK_MODEL / ARK_ENDPOINT_ID

DOUBAO_MAX_RETRIES=3
DOUBAO_RETRY_BASE_SECONDS=5
DOUBAO_RETRY_MAX_SECONDS=60
```

- 当 `LLM_PROVIDER=anthropic` 时，Pipeline 使用 Claude / Anthropic SDK。
- 当 `LLM_PROVIDER=openai` 时，Pipeline 使用 OpenAI Responses API。
- 当 `LLM_PROVIDER=qwen` 时，Pipeline 使用 OpenAI SDK 连接 DashScope 的 OpenAI-compatible Chat Completions API；优先读取 `QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`，同时兼容 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`。
- 当 `LLM_PROVIDER=doubao` 时，Pipeline 使用 OpenAI SDK 连接火山方舟在线推理 `Responses API`；优先读取 `DOUBAO_API_KEY`、`DOUBAO_BASE_URL`、`DOUBAO_MODEL`，同时兼容 `ARK_API_KEY`、`ARK_BASE_URL`、`ARK_MODEL`、`ARK_ENDPOINT_ID`。`DOUBAO_MODEL` 既可以填写基础模型名，也可以直接填写共享 Endpoint ID，例如 `ep-...`。
- `inspect_db` 依赖 `DATABASE_URL` 读取真实数据库 schema，目前支持 SQLite 和 MySQL，只允许只读查询。
- 快速单元测试可运行 `pytest tests/unit`；本地链路集成测试可运行 `pytest tests/integration/engine`；全量非 Prompt 测试可运行 `pytest tests --ignore=tests/prompts`。
- 若要执行真实外部依赖测试，可运行 `pytest tests/integration/external`；其中真实 MySQL 集成测试需要额外设置 `MYSQL_TEST_DATABASE_URL`，也可单独运行 `python -m unittest tests.integration.external.test_inspect_db_mysql_integration`。
- `agents/tools_definition.md` 由 `pipeline/tools_schema.py` 单源生成；修改工具协议后执行 `python scripts/gen_tools_doc.py`，校验一致性可执行 `python scripts/gen_tools_doc.py --check`。
- `rules/skill-routing.md` 由 `rules/skill-routing.yaml` 单源生成；修改路由表后执行 `python scripts/gen_skill_routing_md.py`，校验一致性可执行 `python scripts/gen_skill_routing_md.py --check`（CI 中由 `.github/workflows/skill-routing-doc-check.yml` 自动校验）。
- 飞书事件入口基于 `lark-oapi` SDK 的 WebSocket 长连，URL 校验、verification token、签名与加密均由 SDK 兜底，业务层只负责 24 小时 `header.event_id` 幂等去重。
- LLM 适配层会在 `AgentTurn.usage` 中统一输出 `prompt_tokens`、`completion_tokens`、`total_tokens`、`latency_ms`；OpenAI 与 Doubao 都支持独立的重试配置，Qwen 走 Chat Completions 的工具调用格式。
- **引擎可靠性相关环境变量**（均有合理默认值，按需覆盖）：
  - `LARKFLOW_SESSION_DB`：会话持久化 SQLite 路径，默认 `.larkflow/sessions.db`（已在 `.gitignore` 中忽略）。
  - `LARKFLOW_LOG_FILE`：结构化日志文件路径，默认 `logs/larkflow.jsonl`。
  - `LARKFLOW_LOG_LEVEL`：默认 `INFO`。
  - `AGENT_TURN_TIMEOUT`：单轮 LLM 调用超时（秒），默认 `120`。
  - `AGENT_MAX_RETRIES`：单轮 LLM 调用的指数退避重试次数，默认 `3`。
  - `AGENT_MAX_TURNS`：单阶段最大轮数，超过置 `failed` 并告警，默认 `30`。
  - `AGENT_MAX_EMPTY_STREAK`：连续空响应阈值，超过置 `failed`，默认 `3`。

### 3. 运行

最小启动集是 `pipeline.lark_interaction`。它负责：

- 与飞书建立 WebSocket 长连
- 接收卡片点击审批事件
- 恢复挂起需求并继续跑 coding / testing / reviewing / deploying

启动命令：

```bash
PYTHONPATH=. python -m pipeline.lark_interaction
```

如果希望宿主机运行时的 `stdout/stderr` 也实时进入 `Loki`，建议改用：

```bash
mkdir -p logs
PYTHONPATH=. PYTHONUNBUFFERED=1 python -m pipeline.lark_interaction >> logs/lark_listener.log 2>&1
```

这样 `BitableListener` / `LarkListener` / 飞书 SDK 的控制台输出会持续写入 `logs/lark_listener.log`，再由模板中的 `LarkFlow/templates/kratos-skeleton/otel/promtail-config.yaml`（物化后对应 `demo-app/otel/promtail-config.yaml`）采集到 `Loki`。

注意：

- 这两条命令启动的是同一个 `pipeline.lark_interaction` 服务，只是日志输出位置不同，按照需要执行即可。
- 同一时刻只应保留一个进程；不要同时执行两条命令各起一份实例。
- 如果希望既保留终端查看能力、又让 `Loki` 实时采集，推荐使用重定向到 `logs/lark_listener.log` 的方式，再配合 `tail -f logs/lark_listener.log` 本地查看。

多维表格录入新需求后，由 `pipeline/lark_bitable_listener.py` 通过同一条 WebSocket 长连接收 `drive.file.bitable_record_changed_v1` 事件，自动向配置好的接收方发送「需求启动」卡片——**不再需要公网 HTTP 入口、不再需要单独进程**。

对应环境变量：

```env
LARK_DEMAND_BASE_TOKEN=<Base 的 obj_token；知识库内的 Base 需先用 wiki.get_node 换算>
LARK_DEMAND_TABLE_ID=<需求表 table_id>
# 启动卡片 / 技术方案文档授权的接收方：target 可以是群 chat_id，也可以是某个人的 open_id
LARK_DEMAND_APPROVE_TARGET=<ou_xxx 或 oc_xxx>
# chat_id（发群）或 open_id（发私聊），默认 open_id
LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE=open_id
# 以下三项字段名有默认值，仅在 Base 里列名不同时覆盖
# LARK_DEMAND_STATUS_FIELD=状态
# LARK_DEMAND_ID_FIELD=需求ID
# LARK_DEMAND_DOC_FIELD=需求文档
# 技术方案文档链接回写列名，默认“技术方案文档”
# LARK_TECH_DOC_FIELD=技术方案文档
# 可选：指定新建 docx 落到哪个飞书文件夹；未配置时落在 bot 根目录
# LARK_TECH_DOC_FOLDER_TOKEN=
# 可选：覆盖默认文档域名，默认 https://feishu.cn
# LARK_DOC_DOMAIN=https://feishu.cn
```

需求 Base 的最低要求：
- 有 `状态` 单选列（选项需包含：`待启动 / 已发卡 / 处理中 / 已启动 / 驳回 / 失败`）
- 有 `需求ID` 列（自增编号或其他业务唯一键；留空会 fallback 到 record_id）
- 有 `需求文档` 列（作为"完成信号"：填入内容后才发卡，避免新增空行就触发）

飞书开放平台侧需要：`docs:event:subscribe` + `bitable:app` + `bitable:app:readonly` scope；事件订阅里勾选「多维表格记录变更」；机器人被加为该 Base（或所在 wiki 空间）的协作者/成员。

也可以通过 Docker 构建并启动（无需发布端口，容器主动连飞书）。
下面的命令假设当前目录是仓库根目录 `LarkFlow/`：

```bash
docker build -t larkflow LarkFlow/
docker run --rm --env-file LarkFlow/.env larkflow
```

这两条命令分别等价于：

- `docker build -t larkflow LarkFlow/`
  - 使用 [LarkFlow/Dockerfile](/Users/tao/PyCharmProject/LarkFlow/LarkFlow/Dockerfile) 构建服务镜像
- `docker run --rm --env-file LarkFlow/.env larkflow`
  - 在容器里启动默认入口 `python -m pipeline.lark_interaction`

注意：

- 上面的 `docker run` 只会启动 `python -m pipeline.lark_interaction`
- 当前默认模式下，`lark_interaction` 会建立飞书 WebSocket 长连，因此**不需要** `-p 8000:8000` 这类端口映射
- 启动成功后，日志里应看到类似：
  - `[LarkListener] WebSocket 长连已启动，等待飞书事件...`
  - `[Lark] ... connected to wss://msg-frontier.feishu.cn/ws/v2 ...`
- 当前项目的飞书需求启动、审批回调和后续流程恢复，都走同一条 SDK WebSocket 长连链路，不再需要单独的 HTTP 启动入口

如果希望保留 session 数据、日志和生成产物，推荐挂载 volume：

```bash
docker run --rm \
  --env-file LarkFlow/.env \
  -v "$PWD/demo-app:/demo-app" \
  -v "$PWD/LarkFlow/.larkflow:/app/.larkflow" \
  -v "$PWD/LarkFlow/logs:/app/logs" \
  larkflow
```

其中：

- `demo-app`：保存生成产物，便于宿主机继续查看和调试
- `LarkFlow/.larkflow`：保存 session SQLite、运行态状态
- `LarkFlow/logs`：保存结构化日志文件

如果团队需要使用稳定、可控的镜像源，当前支持通过环境变量统一配置构建参数：

```env
LARKFLOW_GO_IMAGE=registry.example.com/library/golang:1.22-alpine
LARKFLOW_ALPINE_MIRROR=https://mirrors.example.com/alpine
LARKFLOW_GO_PROXY=https://goproxy.cn,https://proxy.golang.org,direct
LARKFLOW_PYTHON_IMAGE=registry.example.com/library/python:3.11-slim
LARKFLOW_DEBIAN_MIRROR=https://mirrors.example.com/debian
LARKFLOW_DEBIAN_SECURITY_MIRROR=https://mirrors.example.com/debian-security
```

其中：

- `LARKFLOW_GO_IMAGE`、`LARKFLOW_ALPINE_MIRROR`、`LARKFLOW_GO_PROXY` 由 `pipeline/deploy_strategy.py` 在部署 `demo-app` 时自动读取并注入 `docker build --build-arg`
- `LARKFLOW_PYTHON_IMAGE`、`LARKFLOW_DEBIAN_MIRROR`、`LARKFLOW_DEBIAN_SECURITY_MIRROR` 用于构建 LarkFlow 服务自身镜像，需要在执行 `docker build` 时显式传入

例如，构建 LarkFlow 服务自身镜像时可以执行：

```bash
docker build \
  --build-arg PYTHON_IMAGE=registry.example.com/library/python:3.11-slim \
  --build-arg DEBIAN_MIRROR=https://mirrors.example.com/debian \
  --build-arg DEBIAN_SECURITY_MIRROR=https://mirrors.example.com/debian-security \
  -t larkflow LarkFlow/
```

如果构建时拉取 `python:3.11-slim` 超时，可先执行 `docker pull python:3.11-slim`，或检查 Docker Desktop 代理/网络配置。

**飞书开发者后台配置**：在"应用 → 事件与回调 → 推送方式"中选择 **长连接**（不再需要填写 HTTPS 回调 URL、ngrok 隧道、反向代理或证书）；开通应用相关权限（消息、文档、表格等）。

**连通性自检**：

```bash
# 1) 鉴权与网络：返回 bot_name 与 open_id 即表示 SDK 已打通
PYTHONPATH=. python scripts/smoke_lark_sdk.py auth
# 2) 真发文本消息到 LARK_CHAT_ID
PYTHONPATH=. python scripts/smoke_lark_sdk.py send "SDK 冒烟"
# 3) 启动 WebSocket 长连并等待一次卡片点击
PYTHONPATH=. python scripts/smoke_lark_sdk.py ws
```

通过飞书表格即可启动需求：

![image-20260418163029819](./image/image.png)

### 4.简单测试

简单测试：你可以直接运行引擎脚本来模拟一个需求的完整生命周期：（不会向飞书发送技术方案卡片）

```bash
python pipeline/engine.py
```

---

## 本地可观测性

当前仓库已经补齐一套本地可运行的最小可观测性方案，目标是同时覆盖：

- `demo-app` 的 HTTP / gRPC trace
- `LarkFlow` 主流程的关键 span
- 容器日志与 `LarkFlow/logs/larkflow.jsonl` 文件日志

### 1. 组件与目录

版本控制中的 source of truth 位于 `LarkFlow/templates/kratos-skeleton/otel/`，每次物化骨架后会出现在 `demo-app/otel/`。本地编排文件包括：

- `docker-compose.yml`：本地观测栈入口
- `otel-collector-config.yaml`：OTLP 接收与转发配置
- `tempo.yaml`：trace 存储
- `prometheus.yml`：metrics 抓取配置
- `loki-config.yaml`：日志存储
- `promtail-config.yaml`：容器日志与文件日志采集

当前 `docker-compose.yml` 会启动：

- `demo-app`
- `otel-collector`
- `tempo`
- `grafana`
- `prometheus`
- `loki`
- `promtail`

### 2. 启动本地 OTEL 栈

在骨架已物化为 `demo-app/` 后，在仓库根目录执行：

```bash
cd demo-app/otel
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
```

启动后默认访问地址：

- `demo-app`：`http://localhost:8080`
- `Grafana`：`http://localhost:3000`
- `Prometheus`：`http://localhost:9090`
- `Tempo`：`http://localhost:3200`
- `Loki`：`http://localhost:3100`

说明：

- `http://localhost:8080/` 返回 `404` 是正常的，根路径未注册。
- `http://localhost:3200/` 和 `http://localhost:3100/` 返回 `404` 也正常，`Tempo` 和 `Loki` 主要提供 API，不提供首页 UI。
- `Grafana` 默认账号密码是 `admin / admin`。

### 3. 如何验证 trace

需要区分两种场景：

- **模板空骨架**：新物化出来的 `demo-app` 默认不注册任何业务路由，因此 `http://localhost:8080/` 以及 `/v1/greeter/tao` 返回 `404` 都是正常的；这只能证明服务进程已启动，不能用来验证业务接口。
- **业务化 demo-app**：如果当前 `demo-app/` 已经生成了 `Greeter` 等示例接口，再使用对应路由做 trace 验证。

如果你当前运行的是带 `Greeter` 示例的业务化 `demo-app`，可以执行：

```bash
curl http://localhost:8080/v1/greeter/tao
curl http://localhost:8080/v1/greeter/test
```

随后在 `Grafana -> Explore -> Tempo` 中查询 `demo-app` 的最新 trace。具体 operation 名称取决于当前物化项目里实际注册了哪些 HTTP/gRPC 服务，不应再假定一定是 `/greeter.v1.Greeter/SayHello`。

查看更详细的 span 信息时：

1. 进入 `Grafana -> Explore`
2. 数据源选择 `Tempo`
3. 点击一条 `Trace ID`
4. 再点击具体 span
5. 在详情面板查看 `Attributes`、`Resource attributes`、`Events`

### 4. 如何验证日志

`Loki` 已接入两类日志：

- Docker 容器日志
- `LarkFlow/logs/larkflow.jsonl` 文件日志
- `LarkFlow/logs/*.log` 运行时控制台日志

在 `Grafana -> Explore` 中把数据源切换为 `Loki`，可直接使用这些查询：

```logql
{service="demo-app"}
```

```logql
{service="otel-collector"}
```

```logql
{service="larkflow"}
```

如果你是按上面的推荐命令把 `pipeline.lark_interaction` 输出重定向到了 `logs/lark_listener.log`，可以单独查运行时控制台日志：

```logql
{service="larkflow", filename=~".*lark_listener\\.log"}
```

如果页面为空，优先检查：

- 时间范围是否至少为 `Last 1 hour`
- 是否已重新创建 `grafana` 容器以加载新增数据源

也可以直接用 API 验证 Loki：

```bash
curl http://localhost:3100/ready
curl http://localhost:3100/loki/api/v1/labels
```

### 5. `demo-app` 的最小 OTEL 接入范围

为了尽量不影响原有 Docker 启动链路，`demo-app` 目前只做了最小侵入的 trace 接入：

- 通过 `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量控制是否启用 OTEL
- `cmd/server/main.go` 初始化 tracer provider
- `internal/server/http.go` / `grpc.go` 仅增加 tracing middleware

当前目标是先保证：

- 原有服务能继续启动
- `demo-app -> otel-collector -> tempo -> grafana` 链路可验证

因此这一版没有额外引入：

- 自定义业务 span
- trace 与应用日志的自动关联字段
- `demo-app` 自身的 metrics dashboard

### 6. `LarkFlow` 主流程的最小 OTEL 接入

`LarkFlow` 侧把 OTEL 相关实现集中到了 [LarkFlow/telemetry/otel.py](/Users/tao/PyCharmProject/LarkFlow/LarkFlow/telemetry/otel.py) 和 [LarkFlow/telemetry/hooks.py](/Users/tao/PyCharmProject/LarkFlow/LarkFlow/telemetry/hooks.py)，并在以下位置接入了最小 span：

- `pipeline/lark_interaction.py`
  - `lark.start_request`
  - `lark.card_action`
  - `lark.bitable_record_changed`
- `pipeline/engine.py`
  - `pipeline.start_new_demand`
  - `pipeline.resume_from_phase`
  - `pipeline.resume_after_approval`
  - `phase.design`
  - `phase.coding`
  - `phase.testing`
  - `phase.reviewing`
  - `phase.deploying`
- `pipeline/llm_adapter.py`
  - `llm.call`
- `pipeline/tools_runtime.py`
  - `tool.execute`

这版的定位是“先把主流程看见”，不是完整分布式追踪。当前更适合用：

- `trace` 看流程经过了哪些阶段
- `logs/larkflow.jsonl` 看具体日志正文
- `demand_id` 关联跨阶段信息

### 7. `LarkFlow` 启用 OTEL 的环境变量

在 [LarkFlow/.env.example](/Users/tao/PyCharmProject/LarkFlow/LarkFlow/.env.example) 中已经补充：

```env
OTEL_EXPORTER_OTLP_ENDPOINT=localhost:4317
OTEL_SERVICE_NAME=larkflow
```

说明：

- 宿主机直接启动 `LarkFlow` 时，通常使用 `localhost:4317`
- 如果以后把 `LarkFlow` 也放进 Compose 网络，再改为 `otel-collector:4317`
- 未设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 时，`LarkFlow` OTEL 为 no-op，不影响原有流程

### 8. 当前验收口径

本地可观测性已验证通过的范围是：

- `docker-compose.yml` 能启动 `otel-collector + tempo + grafana + prometheus + loki + promtail + demo-app`
- `demo-app` 可通过 `curl /v1/greeter/{name}` 产生 trace
- `Grafana -> Tempo` 能查到 `demo-app` 的 `SayHello` trace
- `Grafana -> Loki` 能查到 `demo-app`、`otel-collector` 和 `larkflow` 的日志流

当前仍需注意的边界：

- `Tempo` 和 `Loki` 根路径 `404` 属于正常现象
- `demo-app` 根路径 `/` 返回 `404` 也正常
- `LarkFlow` 现在已能发关键流程 span，但还没有把完整日志正文直接嵌进 trace 详情页

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
| `cmd/server/wire.go` | wire DI 汇聚 | 常驻启用 `server/biz/data/service` 四个中心 ProviderSet | — |

### 新增一个 domain（5 步）

```
1. api/order/v1/order.proto              # service Order { rpc CreateOrder ... } + google.api.http
   run_bash: cd demo-app && make api     # 生成 *.pb.go / *_grpc.pb.go / *_http.pb.go
2. internal/biz/order.go                 # OrderUsecase + OrderRepo 接口 + NewOrderUsecase → biz.ProviderSet
3. internal/data/order.go                # orderRepo 实现 biz.OrderRepo + NewOrderRepo → data.ProviderSet
4. internal/service/order.go             # OrderService → service.ProviderSet；在 server 里注册
5. cmd/server/wire.go                    # 保持 biz/data/service.ProviderSet 常驻启用
   run_bash: cd demo-app && python ../LarkFlow/scripts/check_kratos_contract.py . && make wire && make build
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
- 飞书事件走 `lark-oapi` SDK 的 WebSocket 长连，对**出站**网络可达性有要求（默认 `wss://open.feishu.cn`）；对入站不要求公网可达，但代价是一份飞书应用同一时刻只能有一个实例消费事件（多实例需自行做主备或消息再分发）。

## 相关文档

- `LarkFlow/LarkFlow.md`：引擎模块速览。
- `LarkFlow/CHANGELOG.md`：版本变更记录。

## 🔮 未来展望

本框架具备极强的可扩展性与业务适应能力：
- **规范无缝迁移**：未来可轻松接入并适配各公司内部的专属中间件规范与代码风格指南。
- **基建深度打通**：支持通过内部 MCP (Model Context Protocol) 协议，直连生产/测试环境的数据库、缓存及配置中心。
- **CI/CD 自动化闭环**：可直接对接自动化部署流水线，实现测试环境的一键部署，并将详尽的自动化测试报告与运行效果实时回传至飞书卡片。
- **加入业务规则代码**：轻松加入业务规则代码，更加简单的写业务
