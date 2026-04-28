import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.llm_adapter import (
    _create_openai_response_with_retry,
    append_tool_result,
    create_turn,
    get_provider_name,
    initialize_session,
    list_provider_names,
    register_provider,
    reload_provider_registry,
    ToolCall,
)


class FakeAnthropicMessages:
    """模拟 Anthropic messages.create 的最小返回结构。"""

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
    """模拟 Anthropic client，只暴露 llm_adapter 当前需要的 messages 接口。"""

    def __init__(self):
        self.messages = FakeAnthropicMessages()


class FakeOpenAIResponses:
    """模拟 OpenAI Responses API，支持记录调用参数和按顺序吐出响应。"""

    def __init__(self, responses):
        if isinstance(responses, list):
            self.responses = list(responses)
        else:
            self.responses = [responses]
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeOpenAIClient:
    """模拟带有 responses 子对象的 OpenAI 兼容 client。"""

    def __init__(self, responses):
        self.responses = FakeOpenAIResponses(responses)


class FakeQwenCompletions:
    """模拟 Qwen Chat Completions API。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeQwenClient:
    """模拟 DashScope/OpenAI 兼容的 qwen client 入口。"""

    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeQwenCompletions(responses))


class LlmAdapterB6TestCase(unittest.TestCase):
    """覆盖 Provider 注册、usage 归一、重试和工具回填等关键适配行为。"""

    def tearDown(self):
        reload_provider_registry()

    def test_builtin_provider_registry_is_available(self):
        self.assertEqual(
            list_provider_names(),
            ["anthropic", "doubao", "openai", "qwen"],
        )

    def test_register_provider_allows_runtime_extension_until_reload(self):
        register_provider(
            "mock",
            build_client=lambda: "mock-client",
            turn_factory=lambda session, client, system_prompt: SimpleNamespace(
                text_blocks=["mock"],
                tool_calls=[],
                finished=True,
                raw_response=None,
                usage={},
            ),
            model_name_resolver=lambda: "mock-model",
            session_mode="messages",
        )

        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            self.assertEqual(get_provider_name(), "mock")

        reload_provider_registry()
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=False):
            with self.assertRaises(ValueError):
                get_provider_name()

    def test_get_provider_name_rejects_unknown_provider(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}, clear=False):
            with self.assertRaises(ValueError):
                get_provider_name()

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

    def test_create_turn_emits_llm_start_and_end_events_when_logger_present(self):
        session = initialize_session(
            "anthropic",
            "hello",
            FakeAnthropicClient(),
        )
        # 用任意非空对象占位即可；这里测试的是 create_turn 是否走了结构化日志分支，而不是 logger 实现本身。
        session["logger"] = object()

        with patch("pipeline.llm_adapter.log_llm_call_started") as start_mock, \
             patch("pipeline.llm_adapter.log_llm_call_finished") as finish_mock, \
             patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-test"}, clear=False):
            turn = create_turn(session, "system prompt")

        self.assertTrue(turn.finished)
        start_mock.assert_called_once()
        finish_mock.assert_called_once()
        self.assertEqual(start_mock.call_args[0][2], "anthropic")
        self.assertEqual(finish_mock.call_args[0][2], "anthropic")

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

    def test_doubao_turn_supports_shared_endpoint_and_tool_result_roundtrip(self):
        # 第一轮先返回工具调用，第二轮消费 function_call_output 后再返回最终文本。
        tool_response = SimpleNamespace(
            id="resp-doubao-001",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="call-inspect-db",
                    name="inspect_db",
                    arguments='{"query": "SHOW CREATE TABLE users"}',
                )
            ],
            output_text="",
            usage=SimpleNamespace(
                input_tokens=19,
                output_tokens=8,
                total_tokens=27,
            ),
        )
        final_response = SimpleNamespace(
            id="resp-doubao-002",
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(type="output_text", text="doubao done"),
                    ],
                )
            ],
            output_text="",
            usage=SimpleNamespace(
                input_tokens=29,
                output_tokens=4,
                total_tokens=33,
            ),
        )
        client = FakeOpenAIClient([tool_response, final_response])
        session = initialize_session(
            "doubao",
            "hello",
            client,
        )

        with patch.dict(
            os.environ,
            {
                "DOUBAO_MODEL": "ep-20260424-doubao-20-pro",
                "DOUBAO_MAX_RETRIES": "0",
            },
            clear=False,
        ):
            first_turn = create_turn(session, "system prompt")

        self.assertFalse(first_turn.finished)
        self.assertEqual(first_turn.text_blocks, [])
        self.assertEqual(len(first_turn.tool_calls), 1)
        self.assertEqual(first_turn.tool_calls[0].name, "inspect_db")
        self.assertEqual(
            first_turn.tool_calls[0].arguments,
            {"query": "SHOW CREATE TABLE users"},
        )
        self.assertEqual(first_turn.usage["total_tokens"], 27)

        first_call = client.responses.calls[0]
        self.assertEqual(first_call["model"], "ep-20260424-doubao-20-pro")
        self.assertEqual(first_call["instructions"], "system prompt")
        self.assertEqual(first_call["input"], [{"role": "user", "content": "hello"}])
        self.assertEqual(first_call["tools"][0]["type"], "function")

        append_tool_result(
            session,
            ToolCall(
                id="call-inspect-db",
                name="inspect_db",
                arguments={"query": "SHOW CREATE TABLE users"},
            ),
            "DATABASE: mysql\nROWS:\n- table: users",
        )

        with patch.dict(
            os.environ,
            {
                "DOUBAO_MODEL": "ep-20260424-doubao-20-pro",
                "DOUBAO_MAX_RETRIES": "0",
            },
            clear=False,
        ):
            second_turn = create_turn(session, "system prompt")

        self.assertTrue(second_turn.finished)
        self.assertEqual(second_turn.text_blocks, ["doubao done"])
        self.assertEqual(second_turn.tool_calls, [])
        self.assertEqual(second_turn.usage["total_tokens"], 33)

        second_call = client.responses.calls[1]
        self.assertEqual(second_call["previous_response_id"], "resp-doubao-001")
        self.assertEqual(
            second_call["input"],
            [
                {
                    "type": "function_call_output",
                    "call_id": "call-inspect-db",
                    "output": "DATABASE: mysql\nROWS:\n- table: users",
                }
            ],
        )

    def test_openai_retry_handles_generic_exception(self):
        # 这里不用真实 SDK 异常类型，重点验证非限流的瞬时失败也会按统一策略重试一次。
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
        # Qwen 走 Chat Completions 协议，工具结果需要回填成 role=tool 的消息结构。
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
