# LarkFlow Framework

LarkFlow 为一个**完全无头（Headless）、基于多阶段多 Agent（串行）自动化研发工作流引擎**。

[![Version](https://img.shields.io/badge/version-2.4.0-blue.svg)](https://github.com/your-repo/larkflow)
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
- **双入口服务**：`python -m pipeline.app` 在同一进程并行跑飞书 WebSocket 长连 + FastAPI HTTP Server（`uvicorn`），前端 / CI / 其它 bot 可通过 REST 控制整条 pipeline。
- **契约化 REST API + Swagger**：一组 REST 端点覆盖 pipeline 全生命周期（create / start / pause / resume / stop / get / artifact / checkpoint approve・reject / provider 切换 / metrics），`/docs` 即 Swagger UI。
- **可配置 DAG**：四阶段流转由 `pipeline/dag/*.yaml` 描述，当前已内置 `default / feature / bugfix / refactor` 四套模板；除基础阶段顺序外，还可按模板声明 Review 回归策略和是否挂 deploy checkpoint。
- **双 HITL 审批**：设计方案审批 + 部署前审批；两个审批点既可在飞书卡片按钮上完成，也可走 REST `/checkpoints/{cp}/approve|reject`，殊途同归。
- **生命周期 pause / resume / stop**：engine 在 `_run_phase` 与每轮 agent turn 前检查 `cancel_flag / pause_flag`，协作式取消保证数据一致。
- **Provider 运行时切换已接通**：`pipeline/llm/adapter.py` 已把 Anthropic / OpenAI / Qwen / Doubao 的 client 构建、turn 归一和 session mode 收口到 provider registry；`PUT /pipelines/{id}/provider` 现在不仅修改状态，还会真实影响后续 `start` 时使用的 provider。为避免不同 provider 的会话协议不兼容，切换只允许发生在 `create` 后、`start` 前；运行中的 pipeline 再切换会返回冲突错误。
- **LLM 结构化埋点 + metrics 聚合已接通**：`pipeline/ops/observability.py` 与 `llm/adapter.py` 统一输出 `provider / model / tokens_input / tokens_output / duration_ms / retry` 等字段；`GET /metrics/pipelines` 已能基于 `session["metrics"]` 返回真实 token 与耗时聚合，`GET /pipelines/{id}` 在阶段结果落盘后可返回 `stages.design / coding / test / review` 的结构化快照。
- **前端控制台**：`LarkFlow/frontend/` 基于 `Vite + React + TypeScript + MSW` 提供首页、Pipeline 列表页、详情页和仪表盘；列表页和详情页现已可对接真实 `/pipelines` 系列接口，同时保留 MSW 兜底本地演示。
- **浏览器圈选改页面 MVP**：控制台已接入 `picker/` 能力，可在开发态持续圈选前端页面元素，依赖 `data-lark-src`、选区上下文和命名参照生成本地源码预览，并完成确认、回滚、交付摘要、提交前检查、准备提交与安全 commit。

### 1. 整体流转架构

```mermaid
graph TD
    subgraph feishu["飞书入口"]
        F1["Base 新增/编辑需求行"]
        F2["WebSocket 监听飞书事件"]
        F3["读取记录并发送启动卡"]
        F4{"启动卡操作"}
        F5["Base 状态: 驳回"]
    end

    subgraph http["HTTP 入口"]
        H1["前端 / CI / 其它 Bot"]
        H2["POST /pipelines"]
        H3["POST /pipelines/{id}/start"]
        H4["POST /checkpoints/{cp}/approve|reject"]
    end

    subgraph pipeline["LarkFlow Pipeline"]
        P0["start_new_demand<br/>解析需求并物化 Kratos 骨架"]
        P1["Design<br/>生成技术方案并写入飞书文档"]
        P2{"设计审批"}
        P3["Coding<br/>生成/修改 demo-app 代码"]
        P4["Testing<br/>契约校验、构建和测试"]
        P5["Review<br/>代码审查并修复问题"]
        P6{"部署审批"}
        P7["Deploying<br/>docker build / docker run"]
        P8["Done<br/>发送部署结果通知"]
        P9["Stop / Cancel"]
    end

    F1 -->|bitable_record_changed| F2
    F2 --> F3
    F3 --> F4
    F4 -->|开始处理| P0
    F4 -->|驳回| F5

    H1 --> H2 --> H3 --> P0

    P0 --> P1 --> P2
    P2 -->|飞书卡片同意| P3
    H4 -->|design approve| P3
    P2 -->|驳回| P1

    P3 --> P4 --> P5 --> P6
    P6 -->|飞书卡片同意部署| P7
    H4 -->|deploy approve| P7
    P6 -->|取消部署| P9
    P7 --> P8
```

> `python -m pipeline.app` 同进程启动飞书 WebSocket 与 FastAPI。飞书侧通过 Base 事件和卡片按钮进入流程；HTTP 侧通过 REST 创建、启动和审批；两条入口最终都汇入同一个 `engine_api` / `engine` 状态机。

### 2. 目录结构

```text
.
├── README.md
├── doc/                              # 技术方案与阶段计划文档
│   ├── front
│   └── ...
├── LarkFlow/
│   ├── .env.example
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── LarkFlow.md
│   ├── agents/
│   │   ├── phase1_design.md
│   │   ├── phase2_coding.md
│   │   ├── phase3_test.md
│   │   ├── phase4_review.md                 # 单 Agent Review
│   │   ├── phase4_review_security.md        # feature_multi: 安全视角 reviewer
│   │   ├── phase4_review_testing.md         # feature_multi: 测试覆盖 reviewer
│   │   ├── phase4_review_kratos.md          # feature_multi: Kratos 分层 reviewer
│   │   ├── phase4_aggregator.md             # feature_multi: 三路评审仲裁
│   │   └── tools_definition.md
│   ├── config/                      # 与代码解耦的数据化配置
│   │   └── phases.yaml              # engine 各阶段 prompt / kickoff / banner（原 _PHASE_CONFIG）
│   ├── pipeline/
│   │   ├── app.py                    # 双入口：asyncio 并行 WS 长连 + FastAPI
│   │   ├── api/                      # RESTful 控制面
│   │   │   ├── routes.py             # pipeline 端点 + visual-edits 端点 + /healthz + /docs
│   │   │   └── deps.py               # 依赖注入 engine / checkpoint / stage
│   │   ├── config/                   # 统一配置读取层（集中 os.getenv / load_dotenv）
│   │   │   ├── __init__.py           # 首次 import 触发 load_dotenv()
│   │   │   ├── llm.py                # LLM_PROVIDER / ANTHROPIC / OPENAI / QWEN / DOUBAO
│   │   │   ├── lark.py               # LARK_APP_* / LARK_DEMAND_* / LARK_DOC_* 等 15 项
│   │   │   ├── runtime.py            # LARKFLOW_* / UVICORN_* / PIPELINE_HTTP_* / DATABASE_URL
│   │   │   └── phases.py             # 读取 config/phases.yaml，带缓存与必填校验
│   │   ├── core/                     # 引擎内核与会话生命周期
│   │   │   ├── contracts.py          # Pydantic IO 契约（§八 单一事实来源）
│   │   │   ├── engine.py             # 主状态机 / Agent 循环 / 阶段推进
│   │   │   ├── engine_api.py         # 对外 9 方法 facade（REST / WS 共用）
│   │   │   ├── engine_control.py     # 注册表 + cancel/pause/resume + 状态反射
│   │   │   ├── persistence.py        # SqliteSessionStore（.larkflow/sessions.db）
│   │   │   └── subsession.py         # feature_multi 三路 reviewer 子 session 隔离与 metrics 合并
│   │   ├── dag/                      # YAML 驱动的 DAG 模板
│   │   │   ├── default.yaml
│   │   │   ├── feature.yaml
│   │   │   ├── bugfix.yaml
│   │   │   ├── refactor.yaml
│   │   │   ├── feature_multi.yaml
│   │   │   └── schema.py
│   │   ├── lark/                     # 飞书集成层
│   │   │   ├── sdk.py                # 单例 lark-oapi Client 工厂
│   │   │   ├── client.py             # 飞书 IM 消息 / 卡片发送
│   │   │   ├── cards.py              # 设计 / 部署两张审批卡模板（双 HITL）
│   │   │   ├── doc.py                # 读取飞书文档正文
│   │   │   ├── doc_client.py         # 技术方案 docx 创建 / 授权
│   │   │   ├── interaction.py        # WS 长连 + 卡片回调派发 + 事件幂等
│   │   │   └── bitable_listener.py   # Base 记录事件 → 发启动卡 / 回写状态
│   │   ├── llm/                      # 模型调用与本地工具
│   │   │   ├── adapter.py            # 四家 provider registry + turn 归一
│   │   │   ├── tools_schema.py       # Anthropic / OpenAI / Chat Completion 工具协议
│   │   │   ├── tools_runtime.py      # inspect_db / file_editor / run_bash 实现
│   │   │   └── git_tool.py           # 分支 / commit / PR 标题 / 语义摘要封装
│   │   └── ops/                      # 运维 / 观测 / 部署
│   │       ├── observability.py      # 结构化 JSON 日志 + metrics 聚合
│   │       ├── deploy_strategy.py    # DeployStrategy 抽象 + docker-go 策略
│   │       └── visual_edit.py        # 浏览器圈选改页面：预览 / 回滚 / 交付检查 / commit
│   ├── frontend/
│   │   ├── src/
│   │   │   ├── lib/api.ts            # 前端 API 抽象层；包含 visual edit 相关接口
│   │   │   ├── mocks/                # MSW handlers + fixtures + sessionStorage store + metrics builder
│   │   │   ├── pages/                # Home / Pipelines / Pipeline Detail / Dashboard
│   │   │   ├── picker/               # 浏览器圈选、元素定位、浮层交互
│   │   │   │   ├── PickerPanel.tsx   # 自然语言意图、确认/回滚、交付摘要、提交计划
│   │   │   │   ├── locator.ts        # data-lark-src + 邻近上下文 + 命名参照采集
│   │   │   │   └── overlay.ts        # 持续圈选与 hover/selected outline
│   │   │   ├── App.tsx
│   │   │   └── main.tsx
│   │   ├── public/mockServiceWorker.js
│   │   ├── package.json
│   │   └── README.md
│   ├── docs/                         # 用户侧说明文档与截图资产
│   │   ├── Larkflow_frontend_introduction.md
│   │   ├── Larkflow_Grafana_introduction.md
│   │   ├── install.md
│   │   └── assets/
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
│   │       ├── configs/            # 容器内 HTTP 8000 + gRPC 9000
│   │       ├── internal/{biz,conf,data,server,service}/
│   │       ├── otel/               # 本地 Tempo/Loki/Grafana/Prometheus/promtail 编排
│   │       ├── third_party/validate/
│   │       ├── Makefile            # init / api / wire / build / test / run
│   │       └── Dockerfile          # 两阶段 golang:1.22-alpine → alpine:3.19
│   └── tests/
│       ├── unit/
│       │   ├── engine/             # DAG / multi-review / subsession / observability / visual edit
│       │   │   └── test_visual_edit.py
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
- `phase4_review.md`：单 Agent 模式下，从规范角度复查并修正问题（default / feature / bugfix / refactor 模板使用）。

**多视角并行 Review**（`feature_multi` 模板启用）：

- `phase4_review_security.md` / `phase4_review_testing.md` / `phase4_review_kratos.md`：三路只读 reviewer，分别聚焦**安全**、**测试覆盖**、**Kratos 分层**，各自跑独立 agent loop、独立子 session、独立 LLM client，并发度默认 3。
- `phase4_aggregator.md`：仲裁 Agent，读三份子评语合并出最终 `<review-verdict>`。硬规则：任一 role REGRESS 或 failed/cancelled ⇒ 全局 REGRESS；PASS 需三路同时 PASS。仲裁产物仍被既有 `_parse_review_verdict` 解析，回归 Phase 2 Coding 的 `on_failure` 通路零改动。

### 2. Rules 和 Skills

这部分是编码 Agent 的"检索式规范库"：

- `rules/flow-rule.md`：总规则，要求先查路由表再编码；明确"产物是 Kratos 骨架，禁止平铺 .go 文件"。
- `rules/skill-routing.yaml`：**路由表唯一真源**，结构为 `keywords / skill / weight` 列表。权重分三档——**framework `1.3`（架构级硬约束）> domain `1.2`（业务） > 其他 `1.0`**；权重用于上下文排序（命中即读，不再 Top-N 截断）。`defaults` 头条 `skills/framework/kratos.md` 保证每次必读。`rules/skill-routing.md` 作为人类可读镜像并在顶部声明以 YAML 为准。
- **路由执行路径（v2.4 起）**：Phase 1 Agent 在产出设计稿时同步打结构化标签 `tech_tags = {domains, capabilities, rationale}`（见 `agents/phase1_design.md` 的 *Tech Tags Contract*），通过 `ask_human_approval` 回传。Engine 在挂起审批前由 `pipeline/skills/resolver.py` 解析成 `SkillRouting`（tag → 关键词 fallback → defaults 三级回退）并落盘到 session；Phase 2 / Phase 4（含 feature_multi 的三路 reviewer + aggregator）进入各自 `run_agent_loop` 前，`_augment_with_skill_routing` 把 `<skill-routing>` 块注入 system prompt 顶部。下游 Agent 不再自行跑关键词匹配，改为按注入清单顺序读 md。
- `rules/skill-feedback-loop.md`：Phase 4 Reviewer 输出 `<skill-feedback>` 块 → 引擎自动落盘 → 周度 digest → PR 回灌 `skills/*.md` 的四步闭环。`<skill-feedback>` 现携带 `<gap-type>routing|content</gap-type>` 与 `<injected-skills>`，由 `pipeline/skills/feedback.py` 在 Phase 4 结束时追加写入 `tmp/<demand_id>/skill_feedback.jsonl` 与 `telemetry/skill_feedback.jsonl`；`scripts/skill_feedback_digest.py --since 7d` 按 gap type 分桶聚合，区分"路由没覆盖到"和"skill 内容不够"两类问题。
- `skills/**/*.md`：按 `framework/ / lang/ / transport/ / infra/ / governance/ / domain/` 六层组织的知识库，覆盖 Kratos 分层/wire/make 工具链、并发/错误、HTTP/RPC/分页/消息队列、DB/Redis/Config、认证/限流/幂等/日志/韧性/可观测/服务发现，以及订单/用户/支付业务规范。每份 md 保持 🔴 CRITICAL / 🟡 HIGH / 🟢 最佳实践 分级 + Go ❌/✅ 代码对照结构。

### 3. Pipeline

`LarkFlow/pipeline/core/engine.py` 负责主状态机和工具执行：

- 通过 `start_new_demand()` 启动新需求；起点调用 **`_ensure_target_scaffold()`** 把 `templates/kratos-skeleton/` 物化到 `demo-app/`（空目录物化、已物化幂等、脏状态拒绝、模板缺失报错四种情况都在 `tests/unit/engine/test_engine_scaffold.py` 中覆盖）。
- 在设计阶段调用 `ask_human_approval` 后挂起；pipeline 服务重启后 resume 老需求时，scaffold 钩子幂等跳过，Agent 看到的是上次留下的代码。
- 收到审批回调后，按显式状态机 `design → design_pending → coding → testing → reviewing → deploying → done` 推进；任一阶段 LLM 异常 / 超时 / 超轮数 / 连续空响应都会落入 `failed` 并发飞书告警。
- 最后委托 `pipeline/ops/deploy_strategy.py` 的 `DeployStrategy` 完成 Docker 构建与运行；`target_dir` 与策略名从 session 读取，未指定时默认 `demo-app/` + `docker-go` 策略。

引擎可靠性组件：

- `LarkFlow/pipeline/core/persistence.py` 的 `SqliteSessionStore` 把 session 持久化到 `.larkflow/sessions.db`（WAL + 线程锁），进程重启后通过 `list_active()` 列出未完成需求并自动续跑；序列化时自动剥离 `client` / `logger` 等 transient 字段，载入时按 provider 重建。
- `resume_from_phase(demand_id, phase)` 入口支持从 `coding / testing / reviewing / deploying` 任意阶段断点续跑，失败不退回 Phase 1。
- `run_agent_loop` 叠加 `AGENT_TURN_TIMEOUT` 单轮超时、`AGENT_MAX_RETRIES` 指数退避、`AGENT_MAX_TURNS` 最大轮数、`AGENT_MAX_EMPTY_STREAK` 空响应退出四道保护，与 `llm/adapter.py` 中 SDK 层重试解耦。
- `LarkFlow/pipeline/ops/observability.py` 给每个需求发结构化 JSON 日志（stdout + `logs/larkflow.jsonl`），读 `AgentTurn.usage` 累加到 `session["metrics"]`，并统一输出 `provider / model / tokens_input / tokens_output / duration_ms / retry` 等字段，可用 `jq` 按 `demand_id` 聚合 token、延迟与失败重试信息。

`LarkFlow/pipeline/llm/adapter.py` 统一了四类模型调用：

- `Anthropic Messages API`
- `OpenAI Responses API`
- `Qwen/DashScope OpenAI-compatible Chat Completions API`
-  `doubao 1.6/2.0pro`

同时，`llm/adapter.py` 内部已经把 provider 选择从散落的 `if/else` 分发改为 registry 机制，统一管理：

- provider name 归一
- client 初始化
- turn 归一逻辑
- model name 解析
- session mode（`messages` / `pending_inputs`）

这让 engine_api.set_provider(...) 的真实接线、provider 动态扩展以及无重启 reload 都有了稳定的库层落点。

### 4. 前端控制台

`LarkFlow/frontend/` 当前采用 `MSW mock` 方式运行，主要目标是先稳定页面结构、交互流程和契约消费方式。因此，在默认情况下，即使后端服务未启动，前端页面也可以单独运行和演示。在后续的开发中会将 mock 的数据替换为真实的数据。

目前这套控制台已经往真实接口方向迈了一步：

- Pipeline 列表页会主动拉取 `GET /pipelines`，用于展示真实需求描述、状态和更新时间。
- 详情页的 start / pause / resume / stop / provider 切换 / checkpoint 操作都已按真实 REST 契约接线。
- 侧边栏挂入了浏览器圈选入口，开发态下可直接对前端页面做圈选预览和本地源码改动确认。

更具体的内容可以参考这篇文档：[前端说明文档](LarkFlow/docs/Larkflow_frontend_introduction.md)

本地启动命令：

```bash
cd LarkFlow/frontend
npm install
npx msw init public/ --save
npm run dev
```

构建验收命令：

```bash
npm run build
```

### 5. 双入口服务 + 控制面

`LarkFlow/pipeline/app.py` 是生产默认启动入口，通过 `asyncio.gather` 并行跑两条链路，共享同一份 engine / SessionStore / logger：

- **出站**：飞书 WebSocket 长连（`lark_oapi.ws.Client`），订阅卡片点击与多维表格事件（不变）
- **入站**：FastAPI HTTP Server（`uvicorn.Server`），暴露 `pipeline/api/routes.py` 定义的 §八 全量 REST 端点

`LarkFlow/pipeline/core/contracts.py` 是前端、REST、WS 回调共用的**单一事实来源**：

- `Stage = design | coding | test | review` / `StageStatus = success | failed | rejected | pending`
- `PipelineStatus = pending | running | paused | waiting_approval | stopped | failed | rejected | succeeded`
- `CheckpointName = design | deploy`（两个 HITL）
- `PipelineState / StageResult / Checkpoint / MetricsItem` 等模型定义了所有端点响应结构

`LarkFlow/pipeline/core/engine_api.py` 是 9 个方法的 facade，被 REST 路由与 WS 卡片回调共用，两条入口殊途同归：

| 方法 | 对应 REST | WS 入口 |
|---|---|---|
| `create_pipeline / start / pause / resume / stop` | `POST /pipelines` 系列 | — |
| `get_state / get_stage_artifact` | `GET /pipelines/{id}` 系列 | — |
| `approve_checkpoint(DESIGN)` | `POST /checkpoints/design/approve` | 飞书「设计审批」卡按钮 |
| `approve_checkpoint(DEPLOY)` | `POST /checkpoints/deploy/approve` | 飞书「部署审批」卡按钮 |
| `reject_checkpoint` | `POST /checkpoints/{cp}/reject` | 同上的「驳回/取消」按钮 |
| `set_provider` | `PUT /pipelines/{id}/provider` | — |
| `list_metrics` | `GET /metrics/pipelines` | — |

`LarkFlow/pipeline/core/engine_control.py` 给每个 pipeline 维护一份 `cancel_flag / pause_flag threading.Event`；`engine.py` 在 `_run_phase` 入口和 `run_agent_loop` 的每一轮 turn 前调用 `check_lifecycle(demand_id)`，被 `cancel_flag` 触发时抛 `PipelineCancelled` 干净退出，被 `pause_flag` 触发时原地 `wait` 直到 clear。这就是赛题要求的**生命周期 pause / resume / stop**——协作式而非强杀。

`LarkFlow/pipeline/dag/default.yaml` + `dag/schema.py` 是**可配置 DAG**：节点、依赖、checkpoint、Review 回归策略和并行 review 配置由 YAML 描述；`engine.py` 导入期基于 default DAG 通过 `_build_next_phase_from_dag()` 构造 `_NEXT_PHASE`，当前主流程阶段顺序仍按 default 的 Design -> Coding -> Test -> Review 推进。目前内置模板白名单为 `default` / `feature` / `bugfix` / `refactor` / `feature_multi`（并行 review）；新增模板除 YAML 外，还需要加入 `TEMPLATE_NAMES`，并按需补充 prompt、前端入口和测试。

** 多视角并行 Review**（`feature_multi` 模板启用）：`DAGNode` 支持 `prompt_files: {role: prompt}` + `aggregator_prompt_file` + `parallel_workers`，`engine._run_phase` 在 Phase 4 自动分发到 `_run_phase_multi`：

- **子 session 隔离**：`pipeline/core/subsession.py` 按 `{demand}::review::{role}` 命名空间把三路 reviewer 写进同一张 `sessions.db`，每路 `history / metrics / client / logger` 全部独立；Worker 结束后 `finalize_subsession` 标记 `phase=done`，`list_active` 不再返回。
- **并发失败隔离**：`ThreadPoolExecutor(max_workers=3)` 跑三路 `_reviewer_worker`，任一路异常 `as_completed` 端被 catch 成 `{status: failed, error}`，另两路照常完成，仲裁 Agent 见到缺失视角按"视角缺失即 REGRESS"规则裁决。
- **生命周期穿透**：子 session 带 `parent_demand_id`，`run_agent_loop` 取父 id 做 `check_lifecycle`；主 pipeline pause/stop 一触发，三路 reviewer 下一轮 turn 全部干净退出。
- **HITL 硬拦截**：子 session 带 `hitl_disabled=True`，Reviewer 误调 `ask_human_approval` 时运行时直接返回错误 tool result 让 Agent 自纠，不会误触发飞书审批卡。
- **契约软兼容**：`PipelineState.review_multi: Optional[ReviewMultiSnapshot]` + `MetricsItem.by_role: List[RoleMetrics]`，非并行模板两字段为 None/空列表，前端判空不渲染；feature_multi 模板下前端可按 role 拆 token input/output 堆叠柱与 duration。
- **结构化日志按 role 分维**：`observability.get_logger(role=...)` 在 JSON 日志里附带 `role` / `parent_demand_id`，Loki/Grafana 可直接按 `role` label 拆色；OTEL `phase.reviewing` span attr 同样带 role，Tempo 三条子 span 时间线并排展开。

`LarkFlow/pipeline/lark/cards.py` 收敛两张审批卡片模板：

- `build_design_approval_card()`：Phase 1 Design 方案评审（同原有）
- `build_deploy_approval_card()`：Phase 4 Review 通过后的**部署审批**（新增的第 2 HITL）

两张卡片的按钮 value 统一格式 `{checkpoint, action, demand_id}`，`process_card_action` 按 `checkpoint` 字段分发到 `engine_api` 对应方法。**向后兼容**：旧版 design 卡片没有 `checkpoint` 字段，走原有的 `resume_after_approval` 链路，不受影响。

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
- `agents/tools_definition.md` 由 `pipeline/llm/tools_schema.py` 单源生成；修改工具协议后执行 `python scripts/gen_tools_doc.py`，校验一致性可执行 `python scripts/gen_tools_doc.py --check`。
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
- **双入口服务相关环境变量**（`pipeline.app` 生效）：
  - `PIPELINE_HTTP_HOST`：FastAPI 监听 host，默认 `0.0.0.0`。
  - `PIPELINE_HTTP_PORT`：FastAPI 监听 port，默认 `8000`。
  - `UVICORN_LOG_LEVEL`：uvicorn 日志级别 `critical|error|warning|info|debug|trace`，默认 `info`。

### REST 控制面速查（§八 契约）

启动 `pipeline.app` 后可直接通过 curl 操作整条 pipeline，完整契约见 `http://localhost:8000/docs`：

```bash
# 创建 + 启动一条 pipeline
curl -X POST http://localhost:8000/pipelines \
  -H 'Content-Type: application/json' \
  -d '{"requirement":"加一个 Redis 限流接口"}'
# → {"id":"DEMAND-xxxxxxxx"}

curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/start

# 查看当前状态（阶段、审批点、provider、tokens 等）
curl http://localhost:8000/pipelines/DEMAND-xxxxxxxx

# 生命周期控制
curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/pause
curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/resume
curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/stop

# 两个 HITL 审批（与飞书卡片按钮等价）
curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/checkpoints/design/approve
curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/checkpoints/deploy/approve

# 拒绝附原因
curl -X POST http://localhost:8000/pipelines/DEMAND-xxxxxxxx/checkpoints/deploy/reject \
  -H 'Content-Type: application/json' -d '{"reason":"先观察下灰度"}'

# LLM Provider 运行时切换（仅对新 pipeline 生效）
curl -X PUT http://localhost:8000/pipelines/DEMAND-xxxxxxxx/provider \
  -H 'Content-Type: application/json' -d '{"provider":"qwen"}'

# 聚合 metrics
curl http://localhost:8000/metrics/pipelines
```

### 3. 运行

生产默认入口是 `pipeline.app`（双入口）。它负责：

- 与飞书建立 WebSocket 长连（入站事件不变）
- 同时启动 FastAPI HTTP Server，暴露 §八 REST 端点与 Swagger UI
- 接收卡片点击审批事件（Design / Deploy 两个 HITL）
- 恢复挂起需求并继续跑 coding / testing / reviewing / deploying

启动命令：

```bash
PYTHONPATH=. python -m pipeline.app
```

启动后：

- Swagger UI：`http://localhost:8000/docs`
- 健康检查：`curl http://localhost:8000/healthz` → `{"ok":true}`
- HTTP host/port 可通过 `PIPELINE_HTTP_HOST`（默认 `0.0.0.0`）/ `PIPELINE_HTTP_PORT`（默认 `8000`）覆盖
- `uvicorn` 日志级别可通过 `UVICORN_LOG_LEVEL`（默认 `info`）调整

如果希望宿主机运行时的 `stdout/stderr` 也实时进入 `Loki`，建议改用：

```bash
mkdir -p logs
PYTHONPATH=. PYTHONUNBUFFERED=1 python -m pipeline.app >> logs/lark_listener.log 2>&1
```

这样 `BitableListener` / `LarkListener` / `uvicorn` / 飞书 SDK 的控制台输出会持续写入 `logs/lark_listener.log`，再由模板中的 `LarkFlow/templates/kratos-skeleton/otel/promtail-config.yaml`（物化后对应 `demo-app/otel/promtail-config.yaml`）采集到 `Loki`。

> 兼容：历史仅 WS 的启动方式 `python -m pipeline.lark_interaction` 依旧可用，但不会起 HTTP server；推荐全面切到 `pipeline.app` 以启用 REST 控制面与第 2 HITL 的 REST 入口。

注意：

- 同一时刻只应保留一个进程；不要同时执行两条命令各起一份实例。
- 如果希望既保留终端查看能力、又让 `Loki` 实时采集，推荐使用重定向到 `logs/lark_listener.log` 的方式，再配合 `tail -f logs/lark_listener.log` 本地查看。

多维表格录入新需求后，在该行点击「开始需求」按钮（按钮动作配置为更新「触发时间」字段），由 `pipeline/lark/bitable_listener.py` 通过同一条 WebSocket 长连接收 `drive.file.bitable_record_changed_v1` 事件，识别到触发字段变更后，自动向配置好的接收方发送「需求启动」卡片——**不再需要公网 HTTP 入口、不再需要单独进程**。贴链接、改标题、编辑其它字段不会触发发卡。

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
# 按钮触发字段名（按钮的"修改记录"动作需要更新此字段），默认“触发时间”
# LARK_DEMAND_TRIGGER_FIELD=触发时间
# 可选：指定新建 docx 落到哪个飞书文件夹；未配置时落在 bot 根目录
# LARK_TECH_DOC_FOLDER_TOKEN=
# 可选：覆盖默认文档域名，默认 https://feishu.cn
# LARK_DOC_DOMAIN=https://feishu.cn
```

需求 Base 的最低要求：
- 有 `状态` 单选列（选项需包含：`待启动 / 已发卡 / 处理中 / 已启动 / 驳回 / 失败`）
- 有 `需求ID` 列（自增编号或其他业务唯一键；留空会 fallback 到 record_id）
- 有 `需求文档` 列（按钮触发时若该列为空会静默跳过，提示先补文档再点按钮）
- 有 `技术方案文档`列（技术方案会回写到该位置）
- 有 `开始需求` 按钮列 + `触发时间` 字段列（按钮类型字段，动作配置为"修改记录 → 更新触发时间为当前时间"；点击按钮才会触发发卡）

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
  - 在容器里启动默认入口 `python -m pipeline.app`（双入口：WS 长连 + FastAPI）

注意：

- 默认入口已切到 `python -m pipeline.app`；同时启动飞书 WS 长连和 FastAPI HTTP Server。
- WS 长连是**出站**连接，不占入站端口；但 REST 控制面需要容器暴露 `8000`，因此希望从宿主机或前端访问 API 时需追加 `-p 8000:8000`：
  ```bash
  docker run --rm -p 8000:8000 --env-file LarkFlow/.env larkflow
  ```
- 启动成功后，日志里应看到类似：
  - `[LarkListener] WebSocket 长连已启动，等待飞书事件...`
  - `INFO:     Uvicorn running on http://0.0.0.0:8000`
  - `[Lark] ... connected to wss://msg-frontier.feishu.cn/ws/v2 ...`
- 飞书需求启动、审批回调和后续流程恢复，仍全部走 SDK WebSocket 长连链路；REST 端点是等价的外部控制面，两者殊途同归。

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

- `LARKFLOW_GO_IMAGE`、`LARKFLOW_ALPINE_MIRROR`、`LARKFLOW_GO_PROXY` 由 `pipeline/ops/deploy_strategy.py` 在部署 `demo-app` 时自动读取并注入 `docker build --build-arg`
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

### 4.简单测试

简单测试：你可以直接运行引擎脚本来模拟一个需求的完整生命周期：（不会向飞书发送技术方案卡片）

```bash
python pipeline/core/engine.py
```

---

## 本地可观测性

当前仓库已经补齐一套本地可运行的最小可观测性方案，用于集中展示 Pipeline 运行过程中的可观测性数据，帮助开发者和维护人员快速了解需求处理流程的执行状态，并定位运行中的异常问题。主要承载以下能力：
- 展示 Pipeline 各阶段的运行状态
- 查看链路追踪信息（Trace）
- 查看结构化运行日志
- 观察 LLM 调用情况
- 辅助定位失败、重试、卡顿等问题

我们希望 LarkFlow 的运行过程不是黑盒，而是一个可观察、可分析、可排查的问题定位界面。

更加详细的启动和操作流程可以参考这篇文档：[Grafana 介绍文档](LarkFlow/docs/Larkflow_Grafana_introduction.md)


## 核心特性：按需检索 (RAG) 知识库

LarkFlow 的知识库架构由 Phase 1 Agent 在设计阶段产出结构化 `tech_tags`（`domains` + `capabilities`，取值为 `skills/**/*.md` 的 stem），引擎在挂起审批前由 `pipeline/skills/resolver.py` 一次性解析成 skill 清单并写入 session，再把 `<skill-routing>` 块注入 Phase 2 / Phase 4 的 system prompt 顶部——下游 Agent 按注入清单读 md，不再自行跑关键词匹配。`tech_tags` 缺失或出现非法 tag 时自动回退到 `rules/skill-routing.yaml` 的关键词子串匹配 + defaults，保证向后兼容。

例如，当 Phase 1 打出 `capabilities: ["redis", "rate_limit"]` 时，engine 会解析出 `skills/infra/redis.md` + `skills/governance/rate_limit.md` + defaults（含 `skills/framework/kratos.md`），Phase 2 直接按序读取，写出完全符合团队标准的代码。这极大地降低了 Token 消耗并消除了 AI 幻觉。

Phase 4 Reviewer 在发现规则被违反时，会按 `rules/skill-feedback-loop.md` 的契约输出 `<skill-feedback>` 块，并用 `<gap-type>` 区分"路由没覆盖到"（routing gap）与"skill 内容不够"（content gap）。引擎在 reviewing 阶段结束时自动把这些块落盘到 `telemetry/skill_feedback.jsonl`；运行 `python scripts/skill_feedback_digest.py --since 7d --out LarkFlow/docs/SKILL_BACKLOG.md` 即可生成按 gap type 分桶、按复发次数排序的 backlog，驱动后续扩 tag 枚举或补 skill 内容的决策。

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
docker run --rm -p 8080:8000 -p 9000:9000 <image-id>     # 宿主机 HTTP 8080 -> 容器 8000；gRPC 9000
```

---
## 相关文档

- `LarkFlow/LarkFlow.md`：引擎模块速览。
- `LarkFlow/CHANGELOG.md`：版本变更记录。