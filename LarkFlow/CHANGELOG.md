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

## v1.1.0 (2026-04-16)

### Overview
新增 OpenAI provider 支持，Pipeline 现在支持在 Anthropic 与 OpenAI 之间切换。

### Changed
- 新增 `pipeline/llm_adapter.py`，统一 Anthropic 与 OpenAI 两种 provider 的调用接口与会话状态。
- 重构 `pipeline/tools_schema.py`，工具定义支持 Anthropic 和 OpenAI 两种格式输出。
- 重构 `pipeline/engine.py`，去掉 Anthropic 硬编码，改为调用 `llm_adapter` 统一接口。
- 新增 `openai>=1.0.0` 依赖。
- 更新文档与环境变量配置说明。

