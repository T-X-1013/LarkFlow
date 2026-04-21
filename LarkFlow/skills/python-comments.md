# LarkFlow Python 开发注释规范

## 1. 适用范围

当你在 LarkFlow 仓库中编写或修改 Python 代码时，优先遵循本规范。

适用目录主要包括：

- `LarkFlow/pipeline/`
- `LarkFlow/tests/`
- 未来新增的 Python 工具脚本或辅助模块

本规范参考了 `StoneStory-skill` 项目中的 Python 注释规则，并结合 LarkFlow 当前代码结构做了收敛。

## 2. 总原则

注释优先解释以下至少一项：

- 定义
- 职责
- 意图
- 边界
- 不直观行为

不要把代码本身已经表达清楚的语法再重复翻译成中文。

错误示例：

```python
session["pending_approval"] = None
# 把 pending_approval 设为 None。
```

正确示例：

```python
# 审批结果已经回填到历史消息中，此时必须清空挂起态，避免重复恢复同一个节点
session["pending_approval"] = None
```

## 3. 模块说明

模块在“确实需要帮助读者快速建立上下文”时，可以使用模块级 docstring。

以下场景建议加模块级 docstring：

- 独立职责明确的脚本文件
- 对外提供运行时入口的模块
- 未来新增的 `tools/`、`scripts/`、生成器脚本

以下场景优先不加无信息量 docstring：

- 只有少量简单辅助函数的模块
- docstring 只重复模块文件名或目录名

对于带明显输入输出的工具型脚本，模块 docstring 建议说明：

- 模块用途
- 输入
- 输出
- 运行方式

推荐格式：

```python
"""
LarkFlow 工具文档生成脚本。

输入：
1. pipeline/tools_schema.py 中的工具定义

输出：
1. agents/tools_definition.md

用法：
    python scripts/gen_tools_doc.py
"""
```

## 4. 类与函数 docstring

类和函数在满足以下任一条件时，建议写 docstring：

- 对外暴露为稳定接口
- 输入输出不直观
- 会被多处调用
- 存在明确的副作用或边界约束

在 LarkFlow 中，以下代码默认应补齐 docstring 中的 `@params` 和 `@return`：

- `pipeline/` 下的函数
- `tests/` 中作为测试辅助入口的函数
- 有路径、权限、协议、重试、超时、副作用的函数

对于非常简单、完全局部、语义一眼可见的私有 helper，可以酌情省略；但一旦该函数承担边界、约束或运行时职责，就应补齐入参与返回值说明。

docstring 应优先回答：

- 这个对象是做什么的
- 它负责哪一段流程
- 输入是什么
- 返回什么
- 有哪些关键副作用或约束

推荐格式：

```python
def execute(tool_name: str, args: dict, ctx: ToolContext) -> str:
    """
    执行本地工具调用，并返回可回填给 Agent 的文本结果

    @params:
        tool_name: 工具名称，例如 inspect_db、file_editor
        args: 工具参数字典
        ctx: 当前需求的运行时上下文，包含工作区与目标产物目录

    @return:
        返回字符串结果；成功时返回工具输出，失败时返回可读的错误文本
    """
```

如果函数签名和实现都已经非常直观，可不强行补完整背景说明；但在 `pipeline/` 中，除极简单 helper 外，默认仍应补 `@params` 和 `@return`

## 5. 常量注释

模块级常量注释放在定义的上一行，使用 `#`。

正确示例：

```python
# OpenAI 调用的默认最大重试次数
OPENAI_MAX_RETRIES = 3
```

不要写成：

```python
OPENAI_MAX_RETRIES = 3  # OpenAI 调用的默认最大重试次数
```

例外情况：

- 语义上属于成组字段定义时，可使用行尾注释
- 为了与同组字段纵向对齐时，可保留行尾注释

## 6. 成组字段的行尾注释

以下场景允许使用行尾注释：

- `dataclass` 字段
- `NamedTuple` 字段
- 成组配置项
- 协议结构体字段

要求：

- 注释只写字段语义，不写废话
- 多个并列字段的注释尽量纵向对齐

示例：

```python
@dataclass
class ToolContext:
    demand_id: str       # 当前需求 ID
    workspace_root: str  # 允许读取的工作区根目录
    target_dir: str      # 允许写入的目标产物目录
```

## 7. 核心逻辑注释

对关键流程或不直观逻辑，优先使用 `#` 注释写在代码块上方。

适合加注释的地方：

- 状态机阶段切换
- 审批挂起与恢复
- 路径沙盒判定
- 多模型协议归一
- 部署失败分类
- 重试、退避、幂等等边界逻辑

正确示例：

```python
# 这里只允许写入 target_dir，避免 Agent 误改 rules/、skills/ 或 pipeline 代码
_ensure_write_allowed(path, ctx)
```

不推荐：

```python
_ensure_write_allowed(path, ctx)
# 检查是否允许写入。
```

## 8. 对 LarkFlow 特别重要的注释点

在这个仓库里，以下类型的代码建议优先写清楚“为什么”：

- 为什么某个路径允许读但不允许写
- 为什么某个阶段会挂起或恢复
- 为什么某些 provider 的字段要归一化
- 为什么部署失败要按某种规则分类
- 为什么某段兼容逻辑暂时保留

尤其对于“兼容现状但未来要收敛”的代码，要明确写出兼容原因，避免后续维护者误删。

示例：

```python
# 当前 Prompt 仍使用 ../demo-app 作为相对路径协议，因此读权限需要同时覆盖
# workspace_root 和 target_dir；等 Prompt 收敛到新协议后再考虑进一步简化
```

## 9. 禁止事项

避免出现以下低质量注释：

- 把代码逐行翻译一遍
- 注释与代码明显不一致
- 用“这里”“这个”“那个”这类模糊指代但没有上下文
- 写成需求讨论记录而不是代码说明
- 把临时调试结论长期留在正式代码里

不推荐示例：

```python
# 调一下接口
response = client.responses.create(**request_args)
```

更好的写法：

```python
# OpenAI 侧统一走 Responses API，便于工具调用与 previous_response_id 续接保持一致
response = client.responses.create(**request_args)
```

## 10. 句尾规则

注释和 docstring 的最后一句默认不加句号。

适用范围：

- `#` 注释
- 单行 docstring
- 多行 docstring 中的末句
- `@params` 与 `@return` 的说明文本

这样做的目标是统一风格，不是语法要求；如果必须保留代码片段、缩写或外部引用原文，可按原样保留。

## 11. 注释密度要求

默认保持“低密度、高信息量”。

具体要求：

- 简单代码不加注释
- 有边界和约束的代码加注释
- 一段复杂逻辑最多用 1 到 2 条注释说明核心原因
- 避免出现每行都有注释的情况

如果一段代码需要大量注释才能看懂，应优先考虑：

- 拆函数
- 改名
- 收敛条件分支

## 12. 推荐实践

在 LarkFlow 中写注释时，优先按这个顺序思考：

1. 这段代码的职责是否已经能从命名看出来
2. 如果看不出来，是应该改命名还是加注释
3. 如果要加注释，优先解释“为什么这样做”
4. 如果这是稳定接口，再补充 docstring 说明输入输出

一句话原则：

注释不是为了填满文件，而是为了让后来的人在读到边界、协议和兼容逻辑时，不需要重新猜一遍设计意图。
