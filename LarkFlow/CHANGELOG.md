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
