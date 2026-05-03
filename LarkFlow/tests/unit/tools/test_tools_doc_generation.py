import unittest

from pipeline.llm.tools_schema import get_tool_specs
from scripts.gen_tools_doc import (
    AUTO_GENERATED_HEADER,
    check_tools_definition,
    render_tools_definition_markdown,
)
from tests.path_utils import project_root


class ToolsDocGenerationTestCase(unittest.TestCase):
    def setUp(self):
        self.project_root = project_root()
        self.tools_doc_path = self.project_root / "agents" / "tools_definition.md"

    def test_tools_definition_has_auto_generated_header(self):
        content = self.tools_doc_path.read_text(encoding="utf-8")

        self.assertTrue(content.startswith(AUTO_GENERATED_HEADER))

    def test_tools_definition_matches_generated_content(self):
        expected = render_tools_definition_markdown(get_tool_specs())
        actual = self.tools_doc_path.read_text(encoding="utf-8")

        self.assertEqual(actual, expected)

    def test_check_tools_definition_reports_in_sync(self):
        self.assertTrue(check_tools_definition(self.tools_doc_path))
