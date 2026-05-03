import unittest

from pipeline.llm.tools_schema import (
    get_anthropic_tools,
    get_chat_completion_tools,
    get_openai_tools,
    get_tool_specs,
)


class ToolsSchemaTestCase(unittest.TestCase):
    """验证工具定义单源在不同 Provider 协议下保持一致。"""

    def test_tool_names_are_stable(self):
        """工具名顺序属于协议的一部分，变更时应显式感知。"""
        names = [tool["name"] for tool in get_tool_specs()]
        self.assertEqual(names, ["inspect_db", "file_editor", "ask_human_approval", "run_bash"])

    def test_file_editor_schema_exposes_replace_contract(self):
        """file_editor 的 replace 合约必须暴露给模型，避免生成不完整参数。"""
        file_editor = next(tool for tool in get_tool_specs() if tool["name"] == "file_editor")
        schema = file_editor["schema"]

        self.assertEqual(schema["required"], ["action", "path"])
        self.assertEqual(
            schema["properties"]["action"]["enum"],
            ["read", "write", "replace", "list_dir"],
        )
        self.assertIn("Required for 'write' and 'replace' actions", schema["properties"]["content"]["description"])
        self.assertIn("Required ONLY for 'replace' action", schema["properties"]["old_content"]["description"])

    def test_provider_specific_tool_shapes_preserve_schema(self):
        """Anthropic / OpenAI / Chat Completions 的外层包装可以不同，但底层 schema 必须一致。"""
        base_specs = get_tool_specs()
        anthropic_tools = get_anthropic_tools()
        openai_tools = get_openai_tools()
        chat_tools = get_chat_completion_tools()

        self.assertEqual(len(base_specs), len(anthropic_tools))
        self.assertEqual(len(base_specs), len(openai_tools))
        self.assertEqual(len(base_specs), len(chat_tools))

        file_editor_schema = next(tool for tool in base_specs if tool["name"] == "file_editor")["schema"]
        anthropic_schema = next(tool for tool in anthropic_tools if tool["name"] == "file_editor")["input_schema"]
        openai_schema = next(tool for tool in openai_tools if tool["name"] == "file_editor")["parameters"]
        chat_schema = next(
            tool for tool in chat_tools if tool["function"]["name"] == "file_editor"
        )["function"]["parameters"]

        self.assertEqual(anthropic_schema, file_editor_schema)
        self.assertEqual(openai_schema, file_editor_schema)
        self.assertEqual(chat_schema, file_editor_schema)


if __name__ == "__main__":
    unittest.main()
