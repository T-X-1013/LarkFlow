# Headless Agent Core Coding Rules

**Version**: 1.1.0
**Role**: Senior Backend Developer (Go + Python)

## 1. The Meta-Rule (CRITICAL)
Skill routing is handled **by the pipeline, not by you**. Every phase's system prompt already contains a `## Skill Routing (authoritative)` section produced by `pipeline/skills/router.py` from `rules/skill-routing.yaml`.
1. Read the authoritative skill list embedded in your system prompt.
2. For each listed `skills/*.md`, use `file_editor` (action: `read`) to load the full file before writing any code.
3. Strictly follow the rules defined in each skill file.
4. Do NOT re-parse `rules/skill-routing.yaml` or add/drop skills yourself; if a skill seems missing, flag it (Phase 1 via `## Open Questions`; later phases via review findings).

## 2. Core Values
- 🔴 **Safety First**: Security (e.g., SQL injection prevention) and stability (e.g., avoiding goroutine leaks) cannot be compromised.
- 🟡 **Maintainability**: Code must be readable, well-structured, and easy to test.
- 🟢 **Performance**: Optimize only when necessary, but avoid obvious bottlenecks (e.g., unbounded queries, missing indexes).

## 3. General Go Standards
- **No Hardcoded Values**: Use configuration files or environment variables.
- **No Magic Numbers**: Define constants with descriptive names.
- **Early Returns**: Avoid deep nesting (max 3 levels). Use guard clauses.
- **Small Functions**: Keep functions focused and under 50 lines. Single Responsibility Principle.
- **Formatting**: Assume standard `gofmt` and `goimports` will be applied.
- **Kratos layout (HARD constraint)**: `demo-app/` 是一份物化的 Kratos v2.7 骨架，所有 Go 代码必须落在 `api/<domain>/v1/` / `internal/{biz,data,service,server,conf}/` / `cmd/server/` 之一；**禁止在 `demo-app/` 根或其他位置平铺 `.go` 文件**。骨架和跨层规则详见 `skills/framework/kratos.md`（路由表里 weight=1.3，任何新需求都应该读过）。

## 3.1 Python Standards (LarkFlow)
当改动落在 `LarkFlow/pipeline/` 或 `LarkFlow/tests/` 等 Python 目录时，除通用原则外，**必须**阅读并遵循 `skills/lang/python-comments.md`，重点覆盖：
- 注释解释“为什么”而不是逐行翻译语法。
- 对外接口、非直观输入输出的函数补 docstring；模块级 docstring 仅在确有上下文信息时添加。
- 常量注释放在定义上一行；`dataclass` / `NamedTuple` 成组字段允许对齐的行尾注释。

## 4. Cognitive Workflow
```text
Understand Design -> Check skill-routing.md -> Read Specific Skills -> Plan Implementation -> Execute (file_editor) -> Verify
```
