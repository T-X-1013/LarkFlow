import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.llm_adapter import (
    _create_openai_response_with_retry,
    create_turn,
    initialize_session,
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


if __name__ == "__main__":
    unittest.main()
