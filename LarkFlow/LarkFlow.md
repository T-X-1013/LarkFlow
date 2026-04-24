# LarkFlow 框架

LarkFlow 是一个专为 Go 后端开发设计的无头（Headless）、多智能体（Multi-Agent）全自动编程框架。

## 核心架构

LarkFlow 作为一个由 Python Pipeline 驱动的状态机运行，它协调多个 AI 智能体（Agent）来完成从需求设计到代码部署的完整软件工程任务。

### 1. 智能体 (`agents/`)
- **阶段 1 (架构设计)**：分析业务需求，查询数据库表结构，并输出技术设计文档。
- **阶段 2 (编码实现)**：查阅项目规则与技能库，随后使用 `file_editor` 工具实现设计方案。
- **阶段 3 (自动化测试)**：编写单元测试用例并运行 `go test`。
- **阶段 4 (代码审查)**：作为严苛的 Code Reviewer，确保代码质量并严格检查是否遵守了各项规范。

### 2. 规则与技能库 (`rules/` & `skills/`)
本框架采用类似 RAG（检索增强生成）的机制。它不会将所有几万字的规范一股脑塞进 System Prompt 中，而是强制编码 Agent 首先读取 `rules/skill-routing.md` 路由表，根据当前任务的上下文（例如：只有当任务涉及缓存时，才去读取 `skills/infra/redis.md`）来动态发现并学习具体的最佳实践。

### 3. 调度引擎 (`pipeline/`)
这是一个 Python 引擎，负责处理 Anthropic、OpenAI、Qwen/DashScope 或 Doubao/Ark API 的调用，执行本地工具（如文件读写、Bash 命令执行），并通过飞书（Lark）交互式消息卡片来管理整个工作流的挂起（等待人类审批）与唤醒。其中：
- `pipeline/llm_adapter.py` 负责统一 Anthropic、OpenAI、Qwen/DashScope 与 Doubao/Ark 四种 provider 的调用接口与会话状态；Qwen 通过 DashScope 的 OpenAI-compatible Chat Completions API 接入，Doubao 通过火山方舟在线推理 Responses API 接入，并支持 `ep-...` 共享 Endpoint ID 作为 `DOUBAO_MODEL`。
- `pipeline/utils/lark_sdk.py` 提供共享的 `lark-oapi` Client 工厂，出站消息、文档读取、入站事件共用一份 `tenant_access_token` 缓存。
- `pipeline/lark_client.py` 负责飞书卡片构建与消息发送（基于 `client.im.v1.message.create`）。
- `pipeline/lark_interaction.py` 基于 `lark_oapi.ws.Client` 建立 WebSocket 长连，订阅 `card.action.trigger` 事件；URL 校验 / verification token / 签名 / 加密由 SDK 兜底，本文件只做 24 小时 `event_id` 幂等与状态机恢复。

## 快速参考
关于环境配置与部署说明，请参阅 `README.md` 文件。
