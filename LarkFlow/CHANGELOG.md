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
