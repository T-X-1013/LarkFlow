# Headless Agent Core Coding Rules

**Version**: 1.0.0
**Role**: Senior Go Backend Developer

## 1. The Meta-Rule (CRITICAL)
Before implementing ANY specific domain logic (e.g., Database, Cache, HTTP, Concurrency), you **MUST** consult the Skill Routing Table.
1. Read `rules/skill-routing.md` using the `file_editor` tool.
2. Find the relevant keywords for your current task.
3. Read the corresponding `skills/*.md` file to learn the project's standard practices.
4. Strictly follow the rules defined in the skill file.

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

## 4. Cognitive Workflow
```text
Understand Design -> Check skill-routing.md -> Read Specific Skills -> Plan Implementation -> Execute (file_editor) -> Verify
```
