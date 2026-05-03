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
    validate_provider_name,
)


class FakeAnthropicMessages:
    """模拟 Anthropic messages.create 的最小返回结构。"""

    def create(self, **kwargs):
        """
        返回一条固定的 Anthropic 响应。

        @params:
            kwargs: 透传的请求参数，本测试中不做进一步断言

        @return:
            返回带 content、stop_reason 和 usage 的最小响应对象
        """
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
        """
        初始化最小可用的 Anthropic client stub。

        @params:
            无

        @return:
            无返回值；挂载 messages stub
        """
        self.messages = FakeAnthropicMessages()


class FakeOpenAIResponses:
    """模拟 OpenAI Responses API，支持记录调用参数和按顺序吐出响应。"""

    def __init__(self, responses):
        """
        初始化可按顺序返回的 Responses API stub。

        @params:
            responses: 单个响应对象或响应对象列表

        @return:
            无返回值；内部保存响应队列和调用记录
        """
        if isinstance(responses, list):
            self.responses = list(responses)
        else:
            self.responses = [responses]
        self.calls = []

    def create(self, **kwargs):
        """
        记录本次调用参数并弹出下一条预设响应。

        @params:
            kwargs: responses.create 的请求参数

        @return:
            返回预设响应列表中的下一项
        """
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeOpenAIClient:
    """模拟带有 responses 子对象的 OpenAI 兼容 client。"""

    def __init__(self, responses):
        """
        初始化带 responses 子对象的 OpenAI client stub。

        @params:
            responses: 单个响应对象或响应对象列表

        @return:
            无返回值；挂载 FakeOpenAIResponses
        """
        self.responses = FakeOpenAIResponses(responses)


class FakeQwenCompletions:
    """模拟 Qwen Chat Completions API。"""

    def __init__(self, responses):
        """
        初始化 Qwen Chat Completions stub。

        @params:
            responses: 预设响应列表

        @return:
            无返回值；内部保存响应队列和调用记录
        """
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        """
        记录本次调用参数并返回下一条预设响应。

        @params:
            kwargs: chat.completions.create 的请求参数

        @return:
            返回预设响应列表中的下一项
        """
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeQwenClient:
    """模拟 DashScope/OpenAI 兼容的 qwen client 入口。"""

    def __init__(self, responses):
        """
        初始化最小可用的 Qwen client stub。

        @params:
            responses: 预设响应列表

        @return:
            无返回值；挂载 chat.completions stub
        """
        self.chat = SimpleNamespace(completions=FakeQwenCompletions(responses))


class LlmAdapterB6TestCase(unittest.TestCase):
    """覆盖 Provider 注册、usage 归一、重试和工具回填等关键适配行为。"""

    def tearDown(self):
        """
        每个用例结束后重置 provider registry。

        @params:
            无

        @return:
            无返回值；避免运行时注册的 provider 污染后续测试
        """
        reload_provider_registry()

    def test_builtin_provider_registry_is_available(self):
        """验证内置 provider 会在 registry 初始化后稳定可见"""
        self.assertEqual(
            list_provider_names(),
            ["anthropic", "doubao", "openai", "qwen"],
        )

    def test_register_provider_allows_runtime_extension_until_reload(self):
        """验证运行时新增 provider 在 reload 前可用，reload 后会被内置列表覆盖"""
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
        """未知 provider 应立即报错，避免把非法配置带入运行时"""
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}, clear=False):
            with self.assertRaises(ValueError):
                get_provider_name()

    def test_validate_provider_name_normalizes_case_and_spaces(self):
        """provider 名称应允许大小写和前后空格，但最终要归一为稳定值"""
        self.assertEqual(validate_provider_name(" OpenAI "), "openai")

    def test_anthropic_turn_normalizes_usage(self):
        """Anthropic 的 usage 字段应被统一映射为 input/output/total/latency 结构"""
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
        """当 session 带 logger 时，create_turn 应补齐开始和结束两类结构化事件"""
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
        """OpenAI Responses API 的 usage 字段应被统一归一到通用结构"""
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
        """Doubao 应支持工具调用、function_call_output 回填和 previous_response_id 续接"""
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

    def test_doubao_turn_uses_continuation_input_when_pending_inputs_empty(self):
        """Doubao 续接 Responses 链路时不应发送空 input"""
        response = SimpleNamespace(
            id="resp-doubao-continued",
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(type="output_text", text="continued"),
                    ],
                )
            ],
            output_text="",
            usage=SimpleNamespace(
                input_tokens=7,
                output_tokens=3,
                total_tokens=10,
            ),
        )
        client = FakeOpenAIClient(response)
        session = initialize_session(
            "doubao",
            "hello",
            client,
        )
        session["provider_state"]["pending_inputs"] = []
        session["provider_state"]["previous_response_id"] = "resp-doubao-001"

        with patch.dict(
            os.environ,
            {
                "DOUBAO_MODEL": "ep-20260424-doubao-20-pro",
                "DOUBAO_MAX_RETRIES": "0",
            },
            clear=False,
        ):
            turn = create_turn(session, "system prompt")

        self.assertTrue(turn.finished)
        self.assertEqual(turn.text_blocks, ["continued"])
        call = client.responses.calls[0]
        self.assertEqual(call["previous_response_id"], "resp-doubao-001")
        self.assertEqual(
            call["input"],
            [{
                "role": "user",
                "content": "继续执行当前阶段；如果已经完成，请直接给出最终结果。",
            }],
        )

    def test_openai_retry_handles_generic_exception(self):
        """非限流类瞬时失败也应按统一策略重试一次"""
        # 这里不用真实 SDK 异常类型，重点验证非限流的瞬时失败也会按统一策略重试一次。
        response = SimpleNamespace(id="resp-ok")
        calls = []

        class FlakyResponses:
            def create(self, **kwargs):
                """
                首次调用抛错，第二次调用返回成功响应。

                @params:
                    kwargs: responses.create 请求参数

                @return:
                    第二次调用时返回预设成功响应
                """
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
        """Qwen 的 Chat Completions 协议应支持工具调用和 role=tool 回填闭环"""
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
