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
- **工具链重构**：废弃了原有的 `larkflow-*` 内部脚本，统一使用 `pipeline/tools_schema.py` 定义供 Claude API 调用的标准 JSON Schema（包含 `mock_db`, `file_editor`, `run_bash`, `ask_human_approval`）。

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

## v1.3.0 (2026-04-21)

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