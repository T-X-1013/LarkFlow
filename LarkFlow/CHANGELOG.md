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