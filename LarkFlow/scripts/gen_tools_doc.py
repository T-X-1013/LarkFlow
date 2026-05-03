"""
LarkFlow 工具文档生成脚本

输入：
1. pipeline/tools_schema.py 中的工具定义

输出：
1. agents/tools_definition.md

用法：
    python scripts/gen_tools_doc.py
    python scripts/gen_tools_doc.py --check
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DOC_PATH = PROJECT_ROOT / "agents" / "tools_definition.md"

# 直接运行脚本时，显式把仓库根加入 sys.path，确保可以稳定导入 pipeline.llm.tools_schema
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.llm.tools_schema import get_tool_specs


AUTO_GENERATED_HEADER = "<!-- AUTO-GENERATED, DO NOT EDIT -->"


def _format_parameter_type(parameter_schema: dict[str, Any], required: bool) -> str:
    """
    格式化参数类型说明

    @params:
        parameter_schema: 单个参数的 schema 定义
        required: 当前参数是否必填

    @return:
        返回适合放入 Markdown 的类型与必填说明文本
    """
    parameter_type = parameter_schema.get("type", "any")
    parts = [parameter_type, "required" if required else "optional"]

    enum_values = parameter_schema.get("enum") or []
    if enum_values:
        formatted_values = ", ".join(f"`{value}`" for value in enum_values)
        parts.append(f"one of {formatted_values}")

    return ", ".join(parts)


def render_tools_definition_markdown(tool_specs: list[dict[str, Any]]) -> str:
    """
    将工具定义渲染为 Markdown 文档

    @params:
        tool_specs: 从 tools_schema.py 读取到的工具定义列表

    @return:
        返回完整的 tools_definition.md 文本内容
    """
    lines = [
        AUTO_GENERATED_HEADER,
        "",
        "# Headless Agent Tools Definition",
        "",
        "This file is generated from `pipeline/tools_schema.py` by `scripts/gen_tools_doc.py`.",
        "",
        "These are the tools provided by the Pipeline for the LLM provider to call.",
    ]

    for index, tool_spec in enumerate(tool_specs, start=1):
        schema = tool_spec.get("schema", {})
        properties = schema.get("properties", {})
        required_parameters = set(schema.get("required", []))

        lines.extend(
            [
                "",
                f"## {index}. {tool_spec['name']}",
                f"- **Description**: {tool_spec['description']}",
            ]
        )

        if not properties:
            lines.append("- **Parameters**: None")
            continue

        lines.append("- **Parameters**:")
        for parameter_name, parameter_schema in properties.items():
            parameter_type = _format_parameter_type(
                parameter_schema,
                parameter_name in required_parameters,
            )
            description = parameter_schema.get("description", "").strip()
            lines.append(
                f"  - `{parameter_name}` ({parameter_type}): {description}"
            )

    return "\n".join(lines) + "\n"


def write_tools_definition(output_path: Path = TOOLS_DOC_PATH) -> Path:
    """
    生成并写入 tools_definition.md

    @params:
        output_path: 目标 Markdown 文件路径，默认写入 agents/tools_definition.md

    @return:
        返回实际写入的目标文件路径
    """
    content = render_tools_definition_markdown(get_tool_specs())
    output_path.write_text(content, encoding="utf-8")
    return output_path


def check_tools_definition(output_path: Path = TOOLS_DOC_PATH) -> bool:
    """
    校验仓库中的工具文档是否为最新生成结果

    @params:
        output_path: 需要校验的目标 Markdown 文件路径

    @return:
        一致时返回 True；不一致时返回 False
    """
    expected = render_tools_definition_markdown(get_tool_specs())
    actual = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    return actual == expected


def main(argv: Optional[list[str]] = None) -> int:
    """
    运行工具文档生成或一致性校验

    @params:
        argv: 可选命令行参数列表；未传入时从 sys.argv 读取

    @return:
        成功时返回 0；校验失败时返回 1
    """
    parser = argparse.ArgumentParser(
        description="Generate or check agents/tools_definition.md from pipeline/tools_schema.py",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if agents/tools_definition.md is not up to date",
    )
    args = parser.parse_args(argv)

    if args.check:
        if check_tools_definition():
            print(f"Up to date: {TOOLS_DOC_PATH}")
            return 0
        print(
            "agents/tools_definition.md is out of date. "
            "Run `python scripts/gen_tools_doc.py` to regenerate it.",
            file=sys.stderr,
        )
        return 1

    output_path = write_tools_definition()
    print(f"Generated {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
