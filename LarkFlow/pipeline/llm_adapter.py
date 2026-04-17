import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from pipeline.tools_schema import get_anthropic_tools, get_openai_tools


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AgentTurn:
    text_blocks: List[str]
    tool_calls: List[ToolCall]
    finished: bool
    raw_response: Any


def get_provider_name() -> str:
    """读取当前配置的模型提供方"""
    provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    if provider not in {"anthropic", "openai"}:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
    return provider


def build_client(provider: str) -> Any:
    """根据 provider 初始化对应 SDK Client"""
    if provider == "anthropic":
        import anthropic

        api_key = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
        base_url = os.getenv("ANTHROPIC_BASE_URL") or None
        return anthropic.Anthropic(api_key=api_key, base_url=base_url)

    if provider == "openai":
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL") or None
        return OpenAI(api_key=api_key, base_url=base_url)

    raise ValueError(f"Unsupported provider: {provider}")


def initialize_session(provider: str, initial_user_text: str, client: Any) -> Dict[str, Any]:
    """初始化统一的会话状态"""
    session = {
        "provider": provider,
        "client": client,
        "history": [],
        "pending_approval": None,
        "provider_state": {}
    }
    append_user_text(session, initial_user_text)
    return session


def append_user_text(session: Dict[str, Any], text: str):
    """向会话中追加一条用户文本消息"""
    provider = session["provider"]
    session["history"].append({"role": "user", "content": text})

    if provider == "anthropic":
        # Anthropic 直接维护 messages 数组，每轮请求完整传回。
        session["provider_state"].setdefault("messages", []).append({
            "role": "user",
            "content": text
        })
    else:
        # OpenAI Responses API 采用增量输入，因此维护 pending_inputs 队列。
        session["provider_state"].setdefault("pending_inputs", []).append({
            "role": "user",
            "content": text
        })


def append_tool_result(session: Dict[str, Any], tool_call: ToolCall, result_text: str):
    """向会话中追加一条工具执行结果"""
    provider = session["provider"]
    session["history"].append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": result_text
    })

    if provider == "anthropic":
        session["provider_state"].setdefault("messages", []).append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result_text
            }]
        })
    else:
        # OpenAI 需要把工具结果包装成 function_call_output，供下一轮 Responses 请求续接。
        session["provider_state"].setdefault("pending_inputs", []).append({
            "type": "function_call_output",
            "call_id": tool_call.id,
            "output": result_text
        })


def create_turn(session: Dict[str, Any], system_prompt: str) -> AgentTurn:
    """执行一轮模型调用，并返回统一后的结果"""
    provider = session["provider"]
    client = session["client"]

    # 对外暴露统一的 create_turn，内部再按 provider 分发到各自的 SDK 协议。
    if provider == "anthropic":
        return _create_anthropic_turn(session, client, system_prompt)
    return _create_openai_turn(session, client, system_prompt)


def _create_anthropic_turn(session: Dict[str, Any], client: Any, system_prompt: str) -> AgentTurn:
    messages = session["provider_state"].setdefault("messages", [])
    model_name = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    response = client.messages.create(
        model=model_name,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,
        tools=get_anthropic_tools()
    )

    messages.append({"role": "assistant", "content": response.content})

    text_blocks = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            text_blocks.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(
                id=block.id,
                name=block.name,
                arguments=block.input
            ))

    session["history"].append({
        "role": "assistant",
        "content": "\n".join(text_blocks),
        "tool_calls": [
            {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments}
            for tool_call in tool_calls
        ]
    })

    return AgentTurn(
        text_blocks=text_blocks,
        tool_calls=tool_calls,
        finished=response.stop_reason == "end_turn",
        raw_response=response
    )


def _create_openai_turn(session: Dict[str, Any], client: Any, system_prompt: str) -> AgentTurn:
    state = session["provider_state"]
    pending_inputs = list(state.get("pending_inputs", []))
    model_name = os.getenv("OPENAI_MODEL", "gpt-5-codex")

    # OpenAI 侧统一走 Responses API；如果存在 previous_response_id，则继续同一条响应链。
    request_args = {
        "model": model_name,
        "instructions": system_prompt,
        "input": pending_inputs,
        "tools": get_openai_tools(),
        "max_output_tokens": 4096,
    }

    if _model_supports_reasoning(model_name):
        reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "medium").strip()
        if reasoning_effort:
            request_args["reasoning"] = {"effort": reasoning_effort}

    if state.get("previous_response_id"):
        request_args["previous_response_id"] = state["previous_response_id"]

    response = _create_openai_response_with_retry(client, request_args, model_name)
    state["pending_inputs"] = []
    state["previous_response_id"] = response.id

    text_blocks = []
    tool_calls = []
    for item in getattr(response, "output", []):
        item_type = getattr(item, "type", "")
        if item_type == "function_call":
            raw_arguments = getattr(item, "arguments", "") or "{}"
            tool_calls.append(ToolCall(
                id=getattr(item, "call_id", getattr(item, "id", "")),
                name=getattr(item, "name", ""),
                arguments=_safe_json_loads(raw_arguments)
            ))
        elif item_type == "message":
            text_blocks.extend(_extract_openai_message_text(item))

    output_text = getattr(response, "output_text", "")
    if output_text and output_text not in text_blocks:
        text_blocks.append(output_text)

    session["history"].append({
        "role": "assistant",
        "content": "\n".join(text_blocks),
        "tool_calls": [
            {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments}
            for tool_call in tool_calls
        ]
    })

    return AgentTurn(
        text_blocks=text_blocks,
        tool_calls=tool_calls,
        finished=len(tool_calls) == 0,
        raw_response=response
    )


def _model_supports_reasoning(model_name: str) -> bool:
    name = (model_name or "").lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _create_openai_response_with_retry(client: Any, request_args: Dict[str, Any], model_name: str) -> Any:
    from openai import RateLimitError

    max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
    base_delay = float(os.getenv("OPENAI_RETRY_BASE_SECONDS", "5"))
    max_delay = float(os.getenv("OPENAI_RETRY_MAX_SECONDS", "60"))

    for attempt in range(max_retries + 1):
        try:
            return client.responses.create(**request_args)
        except RateLimitError as exc:
            if attempt >= max_retries:
                raise

            retry_after = _extract_retry_after_seconds(str(exc))
            backoff_delay = min(base_delay * (2 ** attempt), max_delay)
            sleep_seconds = min(max(retry_after, backoff_delay), max_delay)
            print(
                f"[LLM] OpenAI rate limited for model {model_name}; "
                f"retrying in {sleep_seconds:.1f}s "
                f"({attempt + 1}/{max_retries})"
            )
            time.sleep(sleep_seconds)


def _extract_openai_message_text(message: Any) -> List[str]:
    texts = []
    for content_item in getattr(message, "content", []):
        content_type = getattr(content_item, "type", "")
        if content_type in {"output_text", "text"}:
            text_value = getattr(content_item, "text", "")
            if text_value:
                texts.append(text_value)
    return texts


def _safe_json_loads(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_arguments": raw}


def _extract_retry_after_seconds(error_text: str) -> float:
    match = re.search(r"Please try again in ([0-9.]+)s", error_text)
    if not match:
        return 0.0

    try:
        return float(match.group(1))
    except ValueError:
        return 0.0
