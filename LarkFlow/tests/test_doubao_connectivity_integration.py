import os
import unittest
from pathlib import Path

from dotenv import load_dotenv

from pipeline.llm_adapter import append_tool_result, build_client, create_turn, initialize_session


class DoubaoConnectivityIntegrationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[1]
        load_dotenv(project_root / ".env", override=False)

    def setUp(self):
        self.api_key = (os.getenv("DOUBAO_API_KEY") or os.getenv("ARK_API_KEY") or "").strip()
        self.model = (
            os.getenv("DOUBAO_MODEL")
            or os.getenv("ARK_MODEL")
            or os.getenv("ARK_ENDPOINT_ID")
            or ""
        ).strip()
        self.base_url = (
            os.getenv("DOUBAO_BASE_URL")
            or os.getenv("ARK_BASE_URL")
            or "https://ark.cn-beijing.volces.com/api/v3"
        ).strip()

        if not self.api_key or not self.model:
            self.skipTest(
                "Doubao credentials are not configured. Set DOUBAO_API_KEY/ARK_API_KEY "
                "and DOUBAO_MODEL/ARK_MODEL/ARK_ENDPOINT_ID in LarkFlow/.env first."
            )

    def test_doubao_provider_returns_real_text_response(self):
        client = build_client("doubao")
        session = initialize_session(
            "doubao",
            os.getenv("DOUBAO_CONNECTIVITY_PROMPT", "请只回复 PONG，不要调用任何工具。"),
            client,
        )

        turn = create_turn(
            session,
            (
                "You are a connectivity probe. "
                "Reply with a very short plain-text answer. "
                "Do not call tools unless absolutely required."
            ),
        )

        self.assertEqual(session["provider"], "doubao")
        self.assertTrue(turn.text_blocks or turn.tool_calls)
        self.assertGreaterEqual(turn.usage["total_tokens"], 0)
        if turn.tool_calls:
            self.fail(
                "The plain connectivity probe unexpectedly triggered tool calls. "
                "The API is reachable, but this probe expects a direct text response."
            )

    def test_doubao_provider_supports_tool_roundtrip(self):
        client = build_client("doubao")
        session = initialize_session(
            "doubao",
            "先调用一个工具，再在收到工具结果后只回复 TOOL_OK。",
            client,
        )

        first_turn = create_turn(
            session,
            (
                "You are a tool-calling probe. "
                "You MUST call exactly one available tool first. "
                "After receiving the tool result, reply with the single token TOOL_OK."
            ),
        )

        self.assertTrue(
            first_turn.tool_calls,
            (
                "Expected at least one tool call. "
                f"model={self.model}, base_url={self.base_url}, text_blocks={first_turn.text_blocks}"
            ),
        )

        append_tool_result(
            session,
            first_turn.tool_calls[0],
            "TOOL_RESULT_OK",
        )

        second_turn = create_turn(
            session,
            (
                "You are a tool-calling probe. "
                "After the tool result arrives, reply with the single token TOOL_OK."
            ),
        )

        self.assertFalse(second_turn.tool_calls)
        self.assertTrue(second_turn.text_blocks)
        self.assertIn("TOOL_OK", "\n".join(second_turn.text_blocks))


if __name__ == "__main__":
    unittest.main()
