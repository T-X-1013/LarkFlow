import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.llm_adapter import (
    _create_openai_response_with_retry,
    append_tool_result,
    create_turn,
    initialize_session,
    ToolCall,
)


class FakeAnthropicMessages:
    def create(self, **kwargs):
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="anthropic done"),
            ],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=11,
                output_tokens=7,
            ),
        )


class FakeAnthropicClient:
    def __init__(self):
        self.messages = FakeAnthropicMessages()


class FakeOpenAIResponses:
    def __init__(self, response):
        self.response = response

    def create(self, **kwargs):
        return self.response


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = FakeOpenAIResponses(response)


class FakeQwenCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeQwenClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeQwenCompletions(responses))


class LlmAdapterB6TestCase(unittest.TestCase):
    def test_anthropic_turn_normalizes_usage(self):
        session = initialize_session(
            "anthropic",
            "hello",
            FakeAnthropicClient(),
        )

        with patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-test"}, clear=False):
            turn = create_turn(session, "system prompt")

        self.assertEqual(turn.usage["prompt_tokens"], 11)
        self.assertEqual(turn.usage["completion_tokens"], 7)
        self.assertEqual(turn.usage["total_tokens"], 18)
        self.assertGreaterEqual(turn.usage["latency_ms"], 0)
        self.assertEqual(session["history"][-1]["usage"], turn.usage)

    def test_openai_turn_normalizes_usage(self):
        response = SimpleNamespace(
            id="resp-001",
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(type="output_text", text="openai done"),
                    ],
                )
            ],
            output_text="",
            usage=SimpleNamespace(
                input_tokens=13,
                output_tokens=5,
                total_tokens=18,
            ),
        )
        session = initialize_session(
            "openai",
            "hello",
            FakeOpenAIClient(response),
        )

        with patch.dict(
            os.environ,
            {
                "OPENAI_MODEL": "gpt-4.1",
                "OPENAI_MAX_RETRIES": "0",
            },
            clear=False,
        ):
            turn = create_turn(session, "system prompt")

        self.assertEqual(turn.text_blocks, ["openai done"])
        self.assertEqual(turn.usage["prompt_tokens"], 13)
        self.assertEqual(turn.usage["completion_tokens"], 5)
        self.assertEqual(turn.usage["total_tokens"], 18)
        self.assertGreaterEqual(turn.usage["latency_ms"], 0)
        self.assertEqual(session["history"][-1]["usage"], turn.usage)

    def test_openai_retry_handles_generic_exception(self):
        response = SimpleNamespace(id="resp-ok")
        calls = []

        class FlakyResponses:
            def create(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    raise RuntimeError("temporary failure")
                return response

        client = SimpleNamespace(responses=FlakyResponses())

        with patch.dict(
            os.environ,
            {
                "OPENAI_MAX_RETRIES": "1",
                "OPENAI_RETRY_BASE_SECONDS": "0",
                "OPENAI_RETRY_MAX_SECONDS": "0",
            },
            clear=False,
        ), patch("pipeline.llm_adapter.time.sleep") as sleep_mock:
            result = _create_openai_response_with_retry(
                client,
                {"model": "gpt-test"},
                "gpt-test",
            )

        self.assertIs(result, response)
        self.assertEqual(len(calls), 2)
        sleep_mock.assert_called_once_with(0.0)

    def test_qwen_turn_supports_tool_call_and_tool_result_roundtrip(self):
        tool_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-inspect-db",
                                function=SimpleNamespace(
                                    name="inspect_db",
                                    arguments='{"query": "SHOW CREATE TABLE users"}',
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=21,
                completion_tokens=9,
                total_tokens=30,
            ),
        )
        final_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="qwen done",
                        tool_calls=None,
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=31,
                completion_tokens=4,
                total_tokens=35,
            ),
        )
        client = FakeQwenClient([tool_response, final_response])
        session = initialize_session(
            "qwen",
            "hello",
            client,
        )

        with patch.dict(os.environ, {"QWEN_MODEL": "qwen-test"}, clear=False):
            first_turn = create_turn(session, "system prompt")

        self.assertFalse(first_turn.finished)
        self.assertEqual(first_turn.text_blocks, [])
        self.assertEqual(len(first_turn.tool_calls), 1)
        self.assertEqual(first_turn.tool_calls[0].name, "inspect_db")
        self.assertEqual(
            first_turn.tool_calls[0].arguments,
            {"query": "SHOW CREATE TABLE users"},
        )
        self.assertEqual(first_turn.usage["total_tokens"], 30)

        first_call = client.chat.completions.calls[0]
        self.assertEqual(first_call["model"], "qwen-test")
        self.assertEqual(first_call["messages"][0], {"role": "system", "content": "system prompt"})
        self.assertEqual(first_call["tool_choice"], "auto")
        self.assertEqual(first_call["tools"][0]["type"], "function")
        self.assertIn("function", first_call["tools"][0])

        append_tool_result(
            session,
            ToolCall(
                id="call-inspect-db",
                name="inspect_db",
                arguments={"query": "SHOW CREATE TABLE users"},
            ),
            "DATABASE: mysql\nROWS:\n- table: users",
        )

        with patch.dict(os.environ, {"QWEN_MODEL": "qwen-test"}, clear=False):
            second_turn = create_turn(session, "system prompt")

        self.assertTrue(second_turn.finished)
        self.assertEqual(second_turn.text_blocks, ["qwen done"])
        self.assertEqual(second_turn.tool_calls, [])
        self.assertEqual(second_turn.usage["total_tokens"], 35)

        second_messages = client.chat.completions.calls[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "call-inspect-db")
        self.assertIn("DATABASE: mysql", second_messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
