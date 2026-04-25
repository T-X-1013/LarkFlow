# Changelog

## v1.0.0 (2026-04-15)

### Overview
重大架构演进：从依赖本地 IDE（Cursor/Claude Code）的辅助插件，彻底重构为**无头（Headless）、API 驱动的 Multi-Agent 自动化研发工作流引擎**。

### Changed
- **架构重构**：引入 Python Pipeline 作为核心调度引擎，接管状态流转。
- **多智能体协作**：将原有的单一 Prompt 拆分为 `agents/` 目录下的 4 个独立 Agent：
  - Phase 1: 架构师 Agent (`phase1_design.md`)
  - Phase 2: 高级开发 Agent (`phase2_coding.md`)
  - Phase 3: 测试 Agent (`phase3_test.md`)
  - Phase 4: 代码审查 Agent (`phase4_review.md`)
- **知识库通用化**：将 `rules/` 和 `skills/` 目录重构为基于开源标准（GORM, Gin, go-redis）的通用 Go 最佳实践。
- **交互层升级**：废弃了本地 IDE 弹窗，新增 `pipeline/lark_interaction.py`，实现真实的飞书（Lark）交互式消息卡片审批与 Webhook 回调。
- **工具链重构**：废弃了原有的 `larkflow-*` 内部脚本，统一使用 `pipeline/tools_schema.py` 定义供 Claude API 调用的标准 JSON Schema（包含 `inspect_db`, `file_editor`, `run_bash`, `ask_human_approval`）。

### Removed
- 删除 `mcp-servers.json`、`.claude/`、`hooks/` 等强绑定本地 IDE 的配置文件。

## v1.1.0 (2026-04-15)

### Overview
修复 Pipeline 交互层的循环依赖问题，并补充 OpenAI provider 支持。

### Changed
- 修复 `pipeline.engine` 与 `pipeline.lark_interaction` 的模块级循环导入问题，从已有的`pipeline/lark_interaction.py`中拆分出`pipeline/lark_client.py`。
- 新增 OpenAI provider 适配，Pipeline 现在支持在 Anthropic 与 OpenAI 之间切换。
- 修复 `README.md` 中的描述问题。 

### Removed
- 无。

## v1.1.1 (2026-04-15)

### Overview
修复 `file_editor.replace` 缺失问题，并同步工具文档描述。

### Changed
- 补齐 `file_editor.replace` 的运行时实现，并同步更新工具文档描述。

### Removed
- 无。

## v1.2.0 (2026-04-18)

### Overview
完善飞书交互链路与部署稳定性，补充飞书文档读取能力，并同步更新环境配置与项目文档。

### Changed
- **飞书消息链路升级**：从单纯 Webhook 发送扩展为支持基于 Bot API 的消息发送，新增 `LARK_APP_ID`、`LARK_APP_SECRET`、`LARK_CHAT_ID` 与 `LARK_RECEIVE_ID_TYPE` 等配置项。
- **审批回调增强**：优化飞书卡片回调解析逻辑，兼容更多事件结构，并补充 `/start` 触发入口，便于从外部请求启动流程。
- **飞书文档读取能力**：新增飞书 `docx` / `wiki` 文档内容拉取能力，Pipeline 可在处理需求时读取飞书文档正文作为设计输入。
- **部署错误诊断改进**：增强 `deploy_app()` 的失败分类与容器日志检查能力，能够更明确地区分镜像拉取、依赖下载、Go 编译、CGO/SQLite、容器启动等问题。
- **LLM 适配增强**：继续完善 OpenAI / Anthropic 统一适配层，补充 OpenAI Responses API 相关处理与限流场景提示。
- **配置与文档同步**：更新 `.env.example`、`README.md` 与 `LarkFlow.md`，补充新的飞书配置方式、目录结构说明和当前能力边界。

### Removed
- **旧飞书配置方式弱化**：不再以单一 `LARK_WEBHOOK_URL` 作为主要消息发送方式，推荐改用飞书应用机器人配置。

## v1.3.0 (2026-04-20)

### Overview
补齐本地工具运行时与受控执行边界，增强文件编辑和命令执行能力，并将数据库探查工具升级为连接真实 SQLite / MySQL 的只读实现

### Changed
- **本地工具运行时接入**：新增 `pipeline/tools_runtime.py`，统一承接 `inspect_db`、`file_editor`、`run_bash` 的本地执行，并在 `pipeline/engine.py` 中接入 `ToolContext` 与工具分发逻辑
- **文件编辑权限收敛**：完善 `file_editor` 的 `read`、`write`、`replace`、`list_dir` 运行时实现；允许读取 `WORKSPACE_ROOT` 与 `target_dir` 下的项目知识和目标代码，写入与替换严格限制在 `target_dir`；同时补齐相对路径规范化、绝对路径拒绝与 `replace` 精确单次匹配校验
- **受控命令执行增强**：为 `run_bash` 新增 `cwd` 与 `timeout` 参数支持，默认超时 60 秒、上限 300 秒；增加危险命令黑名单、超时进程组强杀与 stdout / stderr 输出截断，降低测试和构建阶段的失控风险
- **数据库探查能力升级**：将原有伪造数据库工具替换为真实数据库只读探查工具 `inspect_db`，支持通过 `DATABASE_URL` 连接 SQLite 与 MySQL，并兼容 `SHOW CREATE TABLE`、`DESCRIBE`、`SHOW COLUMNS FROM`、`SHOW TABLES` 等常见 schema 探查语句
- **MySQL 真实联调支持**：新增 MySQL 连接参数解析、`PyMySQL`/`cryptography` 依赖说明与 `MYSQL_TEST_DATABASE_URL` 集成测试入口，支持本地真实 MySQL schema 与样例数据校验
- **测试补齐**：新增并通过 `tests/test_tools_runtime.py`、`tests/test_run_bash.py`、`tests/test_engine_loop_b1.py`、`tests/test_inspect_db.py` 与 `tests/test_inspect_db_mysql_integration.py`，覆盖权限边界、命令执行控制、受控集成链路与 SQLite/MySQL 数据库读取路径
- **文档与规范同步**：更新 `agents/tools_definition.md`、`agents/phase1_design.md`、`README.md`、`.env.example`、`doc/ownership-b.md`，并新增 `doc/python-comment-style.md` 及对应运行时代码注释补齐，统一工具协议、配置示例与注释规范

### Removed
- **废弃旧工具命名**：对外工具名不再使用 `mock_db`，统一改为 `inspect_db`，避免名称继续误导为“伪造数据库”

## v1.3.1 (2026-04-21)

### Overview
收口工具定义文档的生成链路，增强飞书回调安全性与幂等处理，补齐 LLM 调用 usage 观测字段，并让 Docker 镜像能够直接启动当前 FastAPI 服务

### Changed
- **工具定义单源化**：将工具协议定义收敛到 `pipeline/tools_schema.py`，`agents/tools_definition.md` 改为由 `scripts/gen_tools_doc.py` 自动生成，避免工具 schema 与 Markdown 文档长期人工双写
- **工具文档一致性校验**：新增 `.github/workflows/tools-doc-check.yml`，在 GitHub Actions 中执行 `python scripts/gen_tools_doc.py --check`，用于发现手工修改 `agents/tools_definition.md` 或忘记重新生成文档的问题
- **飞书回调安全增强**：完善 `pipeline/lark_interaction.py` 的飞书回调处理，补齐 verification token 校验、签名校验、加密 payload 解密与 `/start` 启动入口兼容
- **飞书事件幂等处理**：基于事件 ID 增加交互回调去重，避免用户多次点击同一张卡片时重复推进同一个审批动作
- **飞书消息发送收口**：将飞书文本消息与卡片消息构造发送逻辑集中到 `pipeline/lark_client.py`，减少 `pipeline/engine.py` 对飞书 API 细节的直接依赖
- **LLM usage 归一记录**：在 `pipeline/llm_adapter.py` 中统一记录 Anthropic 与 OpenAI 返回的 `prompt_tokens`、`completion_tokens`、`total_tokens` 与 `latency_ms`，并写入会话历史，便于后续成本与性能排查
- **OpenAI 重试策略增强**：补充 OpenAI provider 的可配置重试参数，支持通过 `OPENAI_MAX_RETRIES`、`OPENAI_RETRY_BASE_SECONDS`、`OPENAI_RETRY_MAX_SECONDS` 调整限流和临时异常重试行为
- **Docker 运行入口修正**：新增并完善 `Dockerfile`，镜像启动命令统一为 `uvicorn pipeline.lark_interaction:app --host 0.0.0.0 --port 8000`，使容器运行后能够直接提供飞书回调服务
- **部署文档同步**：更新 `README.md` 与 `.env.example`，补充 Docker 构建运行命令、`python:3.11-slim` 预拉取提示、飞书安全配置项和 OpenAI 重试配置项
- **测试覆盖补齐**：新增飞书交互、LLM usage、工具文档生成与 Dockerfile 相关测试，覆盖回调校验、重复事件处理、usage 字段归一、文档生成一致性和容器入口配置

### Removed
- **旧容器启动方式移除**：不再使用过期的 Python 模块启动命令作为 Docker 默认入口，统一通过 Uvicorn 启动 FastAPI 应用

## v1.3.2 (2026-04-22)                                                                                                                                                       
                                                                                                                                                                            
### Overview                                                                                                                                                                 
新增 Qwen provider 支持，补充 Qwen/DashScope 模型提供方说明，让项目文档与当前 `LLM_PROVIDER=qwen` 的实现保持一致                                                                                      
                                                                                                                                                                           
### Changed                                                                                                                                                                  
- **Qwen Provider 文档同步**：更新 `README.md` 与 `LarkFlow.md`，将 LLM Provider 说明从 Anthropic/OpenAI 两类扩展为 Anthropic、OpenAI、Qwen/DashScope 三类                   
- **Qwen 环境变量说明**：在 README 配置示例中补充 `QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`，并说明兼容 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`     
- **Qwen 调用协议说明**：明确 Qwen 通过 DashScope 的 OpenAI-compatible Chat Completions API 接入，工具调用使用 Chat Completions 的 `tools` 与 `role=tool` 回填格式           
                                                                                                                                                                            
### Removed                                                                                                                                                                  
无  

## v1.4.0 (2026-04-21)

### Overview
Agent 能力与规范知识库扩充：skills 库从 6 个扩到 13 个、路由表升级为 YAML 单一真源、四阶段 prompt 统一结构化重写、新增 prompt 评测集与 Reviewer → Skills 回灌闭环。

### Added
- **横切 skills**：新增 `skills/logging.md`、`skills/config.md`、`skills/auth.md`、`skills/rate_limit.md`、`skills/idempotency.md`、`skills/pagination.md`，与既有 `database.md` 等保持 🔴/🟡 分级 + Go ❌/✅ 代码对照结构。
- **业务 skills**：`skills/biz/` 目录下补充 `user.md`（密码 bcrypt、登录防爆破、注册幂等、风控钩子）与 `payment.md`（回调验签 + 幂等、金额 `int64` 分、状态机、对账），风格对齐 `biz/order.md`。
- **路由表 YAML 化**：新增 `rules/skill-routing.yaml` 作为唯一真源，包含 15 条路由与 `defaults` 兜底，业务 skill `weight: 1.2` 优先于横切 1.0。`rules/skill-routing.md` 保留为人类可读镜像并在顶部声明以 YAML 为准。
- **Prompt 评测集**：新增 `tests/prompts/fixtures/` 下 5 个 fixture（简单 CRUD / Redis 缓存 / 分页列表 / 幂等支付回调 / 并发批任务），覆盖工具调用、skills 命中、文件落地、代码正则黑白名单四类断言；配套 `tests/prompts/eval.py` 支持 `--mock`（CI 自检）与真跑入口。
- **Skill 回灌闭环文档**：新增 `rules/skill-feedback-loop.md`，定义 Phase 4 Reviewer 输出 `<skill-feedback>` 结构化块 → 周度 triage → PR 回灌 `skills/*.md` + 路由表 + 评测 fixture 的四步流程。

### Changed
- **四阶段 prompt 全面重写**：`agents/phase1_design.md` / `phase2_coding.md` / `phase3_test.md` / `phase4_review.md` 由 11–24 行扩写到 82–100 行，统一结构为「角色 / 目标 / 工作流 / 禁止事项 / 输出格式 / 示例」。
- **Phase 2 路由行为**：要求 agent 先读 `rules/skill-routing.yaml`，按权重取 Top 5，无匹配时走 defaults，并在写码前报告所选 skill 以便审计。
- **Phase 4 审查输出**：要求 Reviewer 对每个"可沉淀为规则"的发现输出 `<skill-feedback>` 块，供后续回灌 skills 库。

### Removed
- 无。

## v1.4.1 (2026-04-22)

### Overview
按关注点分层重构 `skills/` 目录（PR#1，纯迁移无内容变化），为后续引入 Kratos 相关 skill 打基础。

### Changed
- **skills 目录分层**：从扁平结构迁移为五层结构，使用 `git mv` 保留历史
  - `skills/lang/`：concurrency / error / python-comments
  - `skills/transport/`：http / pagination
  - `skills/infra/`：database / redis / config
  - `skills/governance/`：auth / rate_limit / idempotency / logging
  - `skills/domain/`：原 `skills/biz/`，改名避免与 Kratos `internal/biz` 语义冲突
- **路由与文档同步**：`rules/skill-routing.yaml`、`rules/skill-routing.md`、`rules/skill-feedback-loop.md`、`agents/phase1_design.md`、`agents/phase2_coding.md`、`agents/phase4_review.md`、`tests/prompts/fixtures/*.yaml`、`README.md` 全量更新为新路径
- **代码侧零改动**：`pipeline/tools_runtime.py` 的 ACL 只校验 `workspace_root` 深度无关，无需适配

## v1.4.2 (2026-04-22)

### Overview
引入 Kratos 骨架模板作为每次需求启动时的只读模具，为后续 Agent 按 Kratos 四层布局生成代码铺路。本次仅引入模板（PR#2 / Phase A），不改 pipeline 与 Agent prompt。

### Added
- **`LarkFlow/templates/kratos-skeleton/`**：精简版 Kratos v2.7.3 骨架，覆盖 `api/` / `cmd/server/` / `configs/` / `internal/{biz,conf,data,server,service}` / `third_party/` 目录与 `go.mod` / `Makefile` / `Dockerfile` / `README.md`。
  - 四层 `ProviderSet` 占位（`biz` / `data` / `service` / `server`），`cmd/server/wire.go` 正确汇聚，Agent 只需向对应层追加 provider。
  - `Makefile` 目标：`init` / `api` / `wire` / `build` / `test` / `run` / `all`；`Dockerfile` 两阶段（`golang:1.21-alpine` builder → `alpine:3.19` runtime），HTTP 8080 + gRPC 9000。
  - 默认数据栈：GORM + SQLite（`configs/config.yaml`），与现有 `skills/infra/database.md` 约定一致。
  - 生成物（`*.pb.go` / `wire_gen.go`）不提交，统一由 `make api && make wire` 实时生成。
- **根 `.gitignore` 补充**：排除 `demo-app/`（per-demand 产物目录）以及 demo-app/templates 下的 Kratos 生成物。

### Notes
- 本次**未**改动 `pipeline/engine.py`、Agent prompt、路由表；Phase B（engine 对接 copy-in 钩子）与 Phase C（Agent prompt + `skills/framework/kratos.md`）将在后续 PR 推进。
- 模板 `gofmt -l` 清零；`docker build` 的端到端验证需要宿主能拉取 `golang:1.21-alpine`，留给使用者本地或 CI 侧完成。

## v1.4.3 (2026-04-22)

### Overview
把 Kratos 骨架接入 pipeline：新需求启动时自动把 `templates/kratos-skeleton/` 物化到 `target_dir`（demo-app/），Phase 2 Agent 从完整 Kratos 布局起步（PR#3 / Phase B）。

### Added
- **`_ensure_target_scaffold()` 钩子**：在 `pipeline/engine.py` 的 `start_new_demand` 起点调用；幂等处理四种场景：
  - target_dir 不存在 → `shutil.copytree` 物化模板
  - target_dir 存在但为空 → 先 rmdir 再 copytree
  - target_dir 已有 `go.mod`（resume / 多次 demand） → 原样保留，不覆盖
  - target_dir 非空但缺 `go.mod`（状态不明） → 抛 `RuntimeError` 拒绝覆盖
- **`_resolve_workspace_and_target()`**：统一解析 workspace_root / target_dir，消除 `run_agent_loop` 里的重复计算；start 阶段把两个路径固化进 session，工具调用直接读取。
- **`tests/test_engine_scaffold.py`**：5 个 unittest，覆盖空目录物化、已物化幂等、模板缺失报错、脏状态拒绝四个分支。

### Changed
- `start_new_demand`：物化骨架 → initialize_session → 写入 `target_dir` / `workspace_root` 到 session → 进入 Phase 1。
- `run_agent_loop`：工具执行时从 session 读 `target_dir`（原先是每次重算）。

### Notes
- 仅影响 pipeline 启动行为；Agent prompt 与 skills 未改动（PR#4 / Phase C 处理）。
- 全量回归测试 45 passed（40 旧 + 5 新 scaffold）。

## v1.4.4 (2026-04-22)

### Overview
让 Agent 完整理解 Kratos 骨架——新增 `skills/framework/kratos.md` 作为架构级硬约束（weight=1.3，进 defaults），四阶段 prompt 全部接入 Kratos 分层规则（PR#4 / Phase C）。至此 PR#2→#4 三步闭环，Phase 2 从完整 Kratos 布局起步、按五步流程补业务代码，Phase 4 把跨层违规列为 🔴 红线。

### Added
- **`skills/framework/kratos.md`** 🆕：四层依赖方向矩阵 + 跨层禁例 + 新增 domain 五步流程（proto → biz → data → service → wire 激活）+ wire ProviderSet 累积规则 + Repo interface 放 biz 层的正反例 + proto/errors 组织约定 + Makefile 命令对照 + 常见错配地雷。
- **`tests/prompts/fixtures/06_grpc_order_service.yaml`** 🆕：覆盖 gRPC+HTTP 双协议 + Kratos 五层文件落地 + wire 激活的端到端断言，验证 `skills/framework/kratos.md` 路由命中。

### Changed
- **`rules/skill-routing.yaml` / `skill-routing.md`**：新增 `kratos / wire / 分层 / api 层 / internal/biz|data|service / proto / 骨架 / scaffold` 路由，`weight: 1.3`（高于 business 1.2，高于 generic 1.0）；`defaults` 头条追加 `skills/framework/kratos.md`，保证任何需求都会读到布局规范。
- **`agents/phase1_design.md`**：设计模板新增 `## Kratos Layering` 必填小节，要求每个 usecase 明确拆解到 api/biz/data/service/server/wire 各文件职责；worked example 同步按 user 域重写。
- **`agents/phase2_coding.md`**：Implement 步骤改写为「Kratos 四层布局 + 5 步流程」，明确 `make api` / `make wire` 的触发时机；Forbidden 列表新增跨层调用、根目录平铺、跳过 codegen 三类硬约束。
- **`agents/phase3_test.md`**：Run Tests 顺序强制 `make api && make wire && go test ./...`；worked example 示范 codegen 步骤输出。
- **`agents/phase4_review.md`**：Enforce Standards checklist 新增两组 🔴 红线——跨层 import 违规 + codegen 一致性（proto/ProviderSet 改动后生成物必须同步）。
- **`rules/flow-rule.md`**：General Go Standards 增一条 Kratos 布局硬约束，禁止 `demo-app/` 根目录平铺 .go 文件。

### Notes
- `eval.py --mock` 6/6 fixtures 通过；pytest 全量 45 passed。
- rpc.md / observability.md / resilience.md / service_discovery.md 留给后续 PR#5（同步 PR#2a）——本次只聚焦 Kratos 本身。

## v1.4.5 (2026-04-22)

### Fixed
- **Kratos 骨架 CGO 陷阱**：模板 `gorm.io/driver/sqlite`（底层 mattn/go-sqlite3）依赖 CGO，在 `golang:1.22-alpine` builder 下因未安装 gcc 默认编译为 stub，容器启动时 `gorm.Open` panic：`go-sqlite3 requires cgo to work. This is a stub`。切换到纯 Go 实现的 `github.com/glebarez/sqlite v1.11.0`（drop-in 替换，GORM API 完全兼容），Dockerfile 零改动、alpine 镜像无 gcc 也能正常运行。
- 修改范围：`templates/kratos-skeleton/go.mod`、`templates/kratos-skeleton/internal/data/data.go`。

### Notes
- 五道坑合集（Go 版本 / protobuf-dev / go.sum / 空 ProviderSet / CGO）已沉淀到 memory，下次做 Kratos 骨架直接规避。

## v1.4.6 (2026-04-23)

### Overview
PR#5a：补齐 Kratos 横切治理的第一组 skill —— RPC + Observability + HTTP 改写。Agent 从此能写出"服务间 gRPC 调用 + 端到端 trace + 错误按 errors proto 映射"的生产级代码。韧性（熔断 / 重试 / 超时预算）与服务发现（etcd / nacos）留给 PR#5b。

### Added
- **`skills/transport/rpc.md`** 🆕：Kratos `transport/grpc` + 客户端 `DialInsecure` + tracing.Client / metadata middleware + errors proto 映射 gRPC status + 客户端当 Repo 注入的模式。明确**禁止裸用 `grpc.Dial`**。
- **`skills/governance/observability.md`** 🆕：OpenTelemetry + OTLP gRPC exporter + Kratos tracing/metrics middleware + Prometheus `/metrics`；提供完整的 `setTracerProvider()` 初始化片段；强调 `log.WithContext(ctx)` 是 `trace_id` 注入日志的必要条件；采样率走 env `OTEL_TRACES_SAMPLER_ARG`。
- **`tests/prompts/fixtures/07_inter_service_rpc.yaml`** 🆕：订单 → 库存 gRPC 调用场景；正则断言覆盖 `transport/grpc` / `DialInsecure` / `tracing.Client/Server` / errors proto，黑名单覆盖裸 `grpc.Dial` / `fmt.Errorf` / `gin.Engine`。

### Changed
- **`skills/transport/http.md`**：全面改写。以 Kratos `transport/http` + proto `google.api.http` 注解为主线；Gin/标准库 `net/http` 退场（Reviewer 在 `demo-app/` 里发现即 🔴 block）。明确中间件顺序 `recovery → tracing → logging → 业务`、系统端点 `/healthz` + `/metrics` 的单独挂载方式、protobuf JSON 序列化的 `int64` 字符串化陷阱。
- **`rules/skill-routing.yaml` / `.md`**：新增 `rpc.md`（weight 1.1，关键词 grpc/rpc/服务间调用/...）和 `observability.md`（weight 1.1，关键词 trace/链路/otel/metrics/...）；`defaults` 追加 `observability.md`，保证每次需求都带 trace_id 意识。
- **`agents/phase2_coding.md`** Forbidden 列表新增四条 🔴 规则：裸 `grpc.Dial` / 手工 HTTP 路由 / `fmt.Errorf` 业务错误 / 漏掉 `log.WithContext(ctx)`；都指向对应 skill 的具体章节。

### Notes
- `eval.py --mock` **7/7 fixtures** 通过；pytest 仍 45 passed。
- 骨架 `go.mod` 按保守策略（Q1 选 B）保持最小，新 skill 对应的依赖（opentelemetry / prometheus / kratos tracing 中间件等）由 Agent 在真实需求触发时通过 `go get` 按需引入；`docker build` 阶段的 `go mod tidy` 会同步 `go.sum`。
- PR#5b（resilience / service_discovery）在本 PR 合入观察真实需求产出后再开。

## v1.4.7 (2026-04-23)

### Overview
PR#5b：补齐 Kratos 横切治理的第二组 skill —— 韧性（resilience）与服务发现（service discovery）。至此 PR#5（a+b）全部落地，Agent 已具备写出带熔断/重试/超时预算/注册发现/灰度的生产级微服务的知识基础。

### Added
- **`skills/governance/resilience.md`** 🆕：超时预算（upstream > Σ downstream + 读 `ctx.Deadline` 收敛）、指数退避 + full jitter、Kratos `circuitbreaker` + aegis `sre.NewBreaker` 默认参数、重试/熔断/限流的中间件链路顺序（client 与 server 对称）、selector 节点级熔断。与 `rate_limit.md` / `idempotency.md` 的职责边界在文档里单独列表划清。
- **`skills/governance/service_discovery.md`** 🆕：Kratos `registry.Registrar/Discovery` 抽象 + etcd 实现；服务端 `kratos.Registrar()` + 客户端 `discovery:///svc-name` + `grpc.WithDiscovery(r)`；p2c 为默认负载均衡（禁止改 round_robin）；`filter.Version` 做灰度；优雅下线 + lease TTL 风险；换 nacos/consul 的最小改动点。
- **`tests/prompts/fixtures/08_resilience_retry_budget.yaml`** 🆕：订单→库存 gRPC 调用的韧性组合场景；正则断言覆盖 discovery DSN、熔断阈值、jitter 抖动、codes.Unavailable 重试白名单、`ctx.Deadline` 读取；黑名单禁止固定间隔 sleep、round_robin、裸循环重试。

### Changed
- **`rules/skill-routing.yaml` / `.md`**：新增 `resilience.md`（关键词 熔断/重试/超时预算/退避/韧性，weight 1.0）与 `service_discovery.md`（关键词 服务发现/registry/etcd/nacos/p2c/灰度，weight 1.0）两条路由。

### Notes
- `eval.py --mock` **8/8 fixtures** 通过；pytest 仍 45 passed。
- 骨架 `go.mod` 维持保守策略不预装依赖，韧性和服务发现相关的 Kratos contrib 包（`contrib/registry/etcd/v2` / `aegis/circuitbreaker/sre`）由 Agent 在真实需求触发时 `go get` 引入。
- 至此 PR#1（skills 分层）→ PR#2（模板）→ PR#3（engine scaffold）→ PR#4（Kratos framework skill）→ PR#5a/b（transport + governance）的 Kratos 改造完整落地。下一步建议用真实需求验证 Agent 对 `resilience.md` / `service_discovery.md` 的命中质量，再视情况启动观察期 / skill 回灌 / 引入更多 contrib（trace exporter、消息队列等）。

## v1.5.0 (2026-04-23)

### Overview
引擎内核生产化改造：把进程内存 dict 换成可持久化的 SessionStore、把 `resume_after_approval` 里串成一条线的 Phase 2/3/4 拆成显式状态机 + `resume_from_phase` 断点续跑入口、给 agent loop 加超时/重试/最大轮数/空响应保护、`print()` 全量替换为结构化 JSON logger 并接入 B6 暴露的 `AgentTurn.usage` 指标、把 `deploy_app` 里硬编码的 Go/Docker 分类抽成可替换的 `DeployStrategy`。pipeline 从此支持进程重启恢复与阶段级断点续跑，失败态显式化并带飞书告警。

### Added
- **`pipeline/persistence.py`** 🆕（A1）：`SessionStore` 抽象 + `SqliteSessionStore` 实现（WAL + 线程锁），`get / save / delete / list_active`。序列化时剥离 `client` / `logger` 等 transient 字段，载入时按 `provider` 重建；db 文件位置读 `LARKFLOW_SESSION_DB`，默认 `.larkflow/sessions.db`（已加入 `.gitignore`）。预留 `phase` 列供 A2 使用。
- **`pipeline/observability.py`** 🆕（A4）：`get_logger(demand_id, phase)` 返回带上下文的 JSON logger，双写 stdout + `logs/larkflow.jsonl`（可由 `LARKFLOW_LOG_FILE` 覆盖）；`log_turn_metrics()` 读 `AgentTurn.usage` 打单轮指标事件；`accumulate_metrics()` 把 `prompt_tokens / completion_tokens / total_tokens / latency_ms / turns` 累加到 `session["metrics"]`，跟随 A1 一起持久化，可用 `jq` 聚合。
- **`pipeline/deploy_strategy.py`** 🆕（A5）：`DeployStrategy` 抽象 + `DockerfileGoStrategy`（内聚 Dockerfile 模板 / `docker build`+`run` / 容器健康检查 / 失败分类），加上 `register / get_strategy` 注册表，未知名称回退到 `docker-go`。
- **`tests/conftest.py`** 🆕（A6）：共享 `temp_session_store` / `stub_build_client` / `isolated_log_file` fixture。
- **`tests/test_persistence_a1.py`** 🆕：9 个测试覆盖 CRUD / transient 剥离 / upsert / list_active / 进程重启恢复 / 并发写。
- **`tests/test_state_machine_a2.py`** 🆕：9 个测试覆盖合法性校验 / happy path / 中途挂起 / 断点续跑 / 部署失败 / LLM 异常置 failed / kickoff 注入。
- **`tests/test_loop_reliability_a3.py`** 🆕：7 个测试覆盖超轮数 / 空响应退出 / empty streak 重置 / 单轮超时触发重试 / 通用异常重试耗尽 / 瞬时错误恢复 / `_run_phase` 置 failed。
- **`tests/test_observability_a4.py`** 🆕：5 个测试覆盖 JSON 输出 / `demand_id` 注入 / 调用时 phase 覆盖 / 单轮指标 / 指标累加。
- **`tests/test_deploy_strategy_a5.py`** 🆕 + **`tests/test_deploy_flow_a6.py`** 🆕：16 个测试覆盖 6 种失败分类 / Dockerfile 幂等生成 / 策略注册表 / `deploy_app` 委托 + 自定义 `target_dir` / DockerfileGoStrategy.deploy 主流程 happy path / build 失败 / 容器立即退出。
- **`tests/test_engine_integration_a6.py`** 🆕：7 个端到端集成测试覆盖 `start_new_demand` 挂起 / 审批通过链式跑到 done / 驳回回到 design / 无 pending_approval 的 resume noop / 进程重启 resume / deploy 异常捕获 / run_agent_loop 每轮落盘。

### Changed
- **`pipeline/engine.py`**：
  - **A1**：全局 `SESSION_STORE: Dict` 替换为 `STORE: SessionStore = default_store()`；新增 `_load_session / _save_session` 封装，`_load_session` 自动重建 `client` 与 `logger`。`start_new_demand` / `run_agent_loop` / `resume_after_approval` 在每个状态变更点都 `_save_session`，进程崩溃重启可从 `SqliteSessionStore` 续跑。
  - **A2**：引入 `PHASE_DESIGN / DESIGN_PENDING / CODING / TESTING / REVIEWING / DEPLOYING / DONE / FAILED` 常量 + `_PHASE_CONFIG` / `_NEXT_PHASE` 配置表；抽出 `_advance_to_phase / _run_phase / _mark_failed` 原语；新增 `resume_from_phase(demand_id, phase)` 入口，支持从 coding/testing/reviewing/deploying 任意阶段断点续跑。`resume_after_approval` 瘦身为 thin wrapper。
  - **A3**：`_create_turn_with_retry` 包装 `create_turn`（`ThreadPoolExecutor` + `future.result(timeout=...)`），环境变量 `AGENT_TURN_TIMEOUT`（默认 120s）/ `AGENT_MAX_RETRIES`（默认 3）控制单轮超时与指数退避；`run_agent_loop` 新增 `AGENT_MAX_TURNS`（默认 30）与 `AGENT_MAX_EMPTY_STREAK`（默认 3）硬限，超限抛 `RuntimeError` 由 `_run_phase` 捕获置 `failed`。`_mark_failed` 额外发飞书告警。
  - **A4**：全量 22 处 `print(...)` 替换为结构化 `logger.info/warning/error` + `event` 字段；每轮 turn 后 `log_turn_metrics + accumulate_metrics`；阶段切换打 `phase_enter` 事件。
  - **A5**：`deploy_app` 瘦身 ~70 行到 ~20 行，读 `session["target_dir"]` 与 `session["deploy_strategy"]`，委托 `strategy.deploy(...)` 返回 `DeployOutcome`；删除已转移到策略的 5 个辅助函数（`_run_checked_command / _collect_process_output / _tail_text / _classify_deploy_failure / _inspect_container_failure`）。`deploy_app` 返回 `bool`，让 `resume_from_phase` 能正确置 `done` / `failed`。
- **`tests/test_engine_loop_b1.py`**：迁移到新 `STORE` API，用临时 `SqliteSessionStore` 隔离。
- **`.gitignore`**：新增 `.larkflow/`（A1 会话持久化目录）。

### Validation
- **全量回归**：`pytest tests/ --ignore=tests/test_lark_interaction.py` = **95 passed, 1 skipped**（原 40 + A 系列 55 新增，未回归任何 B/C 的既有测试）。
- **覆盖率**（pytest-cov）：`pipeline/persistence.py` 100% · `pipeline/observability.py` 100% · `pipeline/engine.py` 94% · `pipeline/deploy_strategy.py` 91% · **合计 95%**（PDF 要求 ≥ 70%）。
- **验收对照**：
  - ✅ `python pipeline/engine.py` 启动后 kill 进程，重启可恢复未完成的需求（test_process_restart_recovers_session）
  - ✅ Phase 2/3/4 任意一步抛错可 `resume_from_phase` 从该阶段重试，不退回 Phase 1（test_phase_exception_marks_failed + test_resume_from_reviewing_skips_earlier_phases）
  - ✅ `logs/larkflow.jsonl` 每需求的 token 总数与总耗时可通过 `jq` 聚合（`session["metrics"]` 累加 + 结构化事件）
  - ✅ `deploy_app` 可接收非默认 `target_dir` 正常工作（test_deploy_app_uses_custom_target_dir）

### Notes
- 环境变量新增：`LARKFLOW_SESSION_DB`（默认 `.larkflow/sessions.db`）、`LARKFLOW_LOG_FILE`（默认 `logs/larkflow.jsonl`）、`LARKFLOW_LOG_LEVEL`（默认 `INFO`）、`AGENT_TURN_TIMEOUT`（默认 120）、`AGENT_MAX_TURNS`（默认 30）、`AGENT_MAX_RETRIES`（默认 3）、`AGENT_MAX_EMPTY_STREAK`（默认 3）。
- A3 的 loop 层重试与 `llm_adapter.py` 中 B6 的 `RateLimitError` 重试解耦：B 在 SDK 层兜底瞬时 429，A 在 loop 层兜底更广的网络/SDK 异常与超时。
- `concurrent.futures.ThreadPoolExecutor.result(timeout=...)` 只能让**等待**超时，无法强杀 LLM 调用线程；落盘阶段会短暂阻塞到线程退出。要切换到 `signal.alarm` 或子进程兜底属于更大改造，当前方案叠加 SDK 自带的 connect/read timeout 已能覆盖生产场景。

## v1.5.1 (2026-04-24)

### Overview
新增 Doubao / Ark provider 支持，允许通过火山方舟在线推理 API 与共享 `ep-...` Endpoint 模式接入豆包 2.0 Pro、豆包 1.6。

### Changed
- **Doubao Provider 接入**：在 `pipeline/llm_adapter.py` 中新增 `LLM_PROVIDER=doubao`，并复用 OpenAI SDK 的 Responses API 形态接入火山方舟在线推理。
- **共享 Endpoint 支持**：新增 `DOUBAO_API_KEY`、`DOUBAO_BASE_URL`、`DOUBAO_MODEL`，同时兼容 `ARK_API_KEY`、`ARK_BASE_URL`、`ARK_MODEL`、`ARK_ENDPOINT_ID`；`DOUBAO_MODEL` 允许直接填写 `ep-...`。
- **Responses API 共享逻辑抽象**：OpenAI 与 Doubao 共同复用 Responses API 的会话续接、工具调用回填、usage 归一化与重试逻辑，Doubao 的重试参数独立读取 `DOUBAO_MAX_RETRIES`、`DOUBAO_RETRY_BASE_SECONDS`、`DOUBAO_RETRY_MAX_SECONDS`。
- **接入文档补齐**：新增 `doc/doubao-provider-integration.md`，并同步更新 `README.md`、`.env.example` 与 `LarkFlow.md`，明确在线推理与共享 Endpoint 的配置方式。

## v1.6.0 (2026-04-24)

### Overview
飞书集成从 **FastAPI Webhook + 裸 `requests` 调 Open API** 迁移到 **`lark-oapi` 官方 SDK + WebSocket 长连**。出站消息、文档读取、入站事件全部走 SDK；不再需要公网可达、反向代理、HTTPS 证书，签名/加密/URL 校验由 SDK 兜底。

### Changed
- **SDK 依赖升级**：`requirements.txt` 将 `lark-oapi>=1.1.0` 升级到 `>=1.5.3`，启用 SDK 自带的 token 缓存、WebSocket 客户端与事件分发器。
- **新增共享 SDK 工厂**：`pipeline/utils/lark_sdk.py` 提供单例 `get_lark_client()`，由所有飞书调用方共用一份 `tenant_access_token` 缓存，避免原先每次读文档都多打一次 `auth/v3/tenant_access_token/internal`。
- **`pipeline/lark_client.py` 重写**：删除 `requests.post` 裸调与群机器人 `LARK_WEBHOOK_URL` 分支，统一通过 `client.im.v1.message.create` 发送；`send_lark_card` / `send_lark_text` 对外签名保持不变，`engine.py` 零感知。
- **`pipeline/utils/lark_doc.py` 重写**：`get_tenant_access_token()` 删除；`fetch_lark_doc_content()` 改为 `client.wiki.v2.space.get_node` + `client.docx.v1.document.raw_content`；读文档失败改为抛 `LarkDocError`，不再把错误字符串静默塞进 LLM prompt。
- **`pipeline/lark_interaction.py` 重写**：
  - 删除整个 FastAPI `app`、`/lark/webhook` 路由、`_decrypt_lark_payload` / `_validate_lark_signature` / `_validate_lark_token` / `AESCipher` 等 ~130 行自写校验代码；由 SDK 负责 URL 校验、verification token、签名与加密。
  - 新增 `run_event_loop()` 启动 `lark_oapi.ws.Client` 长连，并通过 `EventDispatcherHandler.register_p2_card_action_trigger` 订阅卡片点击。
  - 保留 24 小时 `event_id` 幂等 SQLite 去重（`LARK_EVENT_STORE_PATH`）、`process_card_action` 业务派发与 `update_card_status` 卡片回写。
- **`engine.py` 去 webhook 兜底**：3 处 `os.getenv("LARK_CHAT_ID") or os.getenv("LARK_WEBHOOK_URL")` 统一改为只读 `LARK_CHAT_ID`；`LARK_WEBHOOK_URL` 不再被引用。
- **Dockerfile 启动命令切换**：`CMD` 从 `uvicorn pipeline.lark_interaction:app --host 0.0.0.0 --port 8000` 改为 `python -m pipeline.lark_interaction`；`EXPOSE 8000` 删除，容器不再需要发布端口。
- **测试迁移**：`tests/test_lark_interaction.py` 从 `fastapi.testclient.TestClient` 改为直接驱动 `process_card_action` 与 `_on_card_action`；URL 校验、签名拒绝两条测试被删（对应代码路径已由 SDK 接管），新增 approve / reject / duplicate dedup / invalid action / unsupported action / SDK 事件解析 6 条用例。
- **冒烟脚本**：新增 `scripts/smoke_lark_sdk.py`，提供 `auth` / `send` / `ws` 三级连通性探针，用于在真实环境验证 SDK 是否能鉴权、发消息与建立 WebSocket 长连。

### Removed
- `LARK_WEBHOOK_URL`：群机器人 webhook URL 旁路已删除，统一走应用 Bot。
- `LARK_VERIFICATION_TOKEN` / `LARK_ENCRYPT_KEY`：不再被代码引用，保留在 `.env.example` 只为向后兼容历史部署。
- `pipeline/lark_interaction.py` 中的 FastAPI 相关代码（`app`、`/lark/webhook`、`/start`、`validate_lark_webhook` 中间件）。
- `pipeline/utils/lark_doc.py` 中的 `get_tenant_access_token()`（由 SDK 内部 token manager 接管）。

### Validation
- **全量回归**：`pytest tests/` = **104 passed, 1 skipped**（对比基线 10 passed 于飞书相关模块，新测试净增 3 条）。
- **连通性验证**：`python scripts/smoke_lark_sdk.py auth` 实机打通，返回 `bot_name` 与 `open_id`，确认 app_id / app_secret / 网络 / token 流转全链路 OK。

### Migration Notes
- **飞书开发者后台**需将事件订阅模式由"HTTPS 回调 URL"改为"**长连接**"（应用 → 事件与回调 → 推送方式），否则飞书仍按 webhook 模式投递而 SDK WebSocket 收不到任何事件。
- **启动命令**：本地 `PYTHONPATH=. python -m pipeline.lark_interaction`；Docker `docker run --env-file .env larkflow`（不再需要 `-p 8000:8000`）。
- **反向代理 / ngrok / HTTPS 证书**在新模式下都可移除；应用向飞书主动建 WebSocket，对出站网络有要求、对入站无要求。
- 已有的 `.larkflow/sessions.db` 与 `tmp/lark_event_store.db` 格式未变，回滚时历史数据可继续消费。
- **测试覆盖补齐**：在 `tests/test_llm_adapter_b6.py` 中新增 Doubao 的共享 Endpoint 与工具调用 roundtrip 单测。

## v1.6.1 (2026-04-25)

### Overview
把 `rules/skill-routing.md` 从手工维护的镜像改造为由 `rules/skill-routing.yaml` 自动生成，彻底落实"YAML 是唯一真源"，并新增 CI 一致性校验。

### Changed
- **YAML schema 扩展**：`rules/skill-routing.yaml` 的每条 route 新增两个可选字段 `display_keywords`（关键词的美化大小写形式，用于镜像表格 Keywords/Domain 列）与 `description`（Description 列一句话说明）；`keywords` 继续保持全小写并用于实际匹配。已把旧 md 中的展示形式与描述回填进 YAML，新老字段对齐无丢失。
- **新增生成脚本**：`LarkFlow/scripts/gen_skill_routing_md.py`，结构对齐 `gen_tools_doc.py`（`render_*` / `write_*` / `check_*` + `--check` 开关），从 YAML 渲染 `rules/skill-routing.md`，权重 ≥ 1.1 自动加粗，表格顺序完全跟随 YAML，并在文件顶部写入 `AUTO-GENERATED FROM rules/skill-routing.yaml, DO NOT EDIT` 标识。
- **镜像文件重建**：`rules/skill-routing.md` 由脚本重新生成，前言措辞更新为"由脚本生成，以 YAML 为准"；Kratos 行从原手工置顶恢复到 YAML 中 framework section 的位置，行内容与权重保持一致。
- **依赖补齐**：`requirements.txt` 新增 `PyYAML>=6.0`，供生成脚本解析 YAML。
- **CI 校验**：新增 `.github/workflows/skill-routing-doc-check.yml`，在 `rules/skill-routing.yaml`、`rules/skill-routing.md` 或生成脚本变更时跑 `python scripts/gen_skill_routing_md.py --check`，防止 YAML 与镜像 md 漂移。
- **文档同步**：更新 `README.md` 目录结构中的 `scripts/` 列表与开发说明段落，明确 skill-routing.md 的生成/校验命令。

### Removed
- 无。

### Migration Notes
- 修改路由表只改 `rules/skill-routing.yaml`，随后运行 `python scripts/gen_skill_routing_md.py` 重新生成镜像 md；直接手改 md 会被 CI `--check` 拦截。

