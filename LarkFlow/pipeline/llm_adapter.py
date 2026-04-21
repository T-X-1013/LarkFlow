import json
import os
import re
import time
from dataclasses import dataclass, field
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
    usage: Dict[str, int] = field(default_factory=dict)


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

    started_at = time.monotonic()
    response = client.messages.create(
        model=model_name,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,
        tools=get_anthropic_tools()
    )
    latency_ms = _elapsed_ms(started_at)
    usage = _normalize_usage(getattr(response, "usage", None), latency_ms)

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
        ],
        "usage": usage,
    })

    return AgentTurn(
        text_blocks=text_blocks,
        tool_calls=tool_calls,
        finished=response.stop_reason == "end_turn",
        raw_response=response,
        usage=usage,
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

    started_at = time.monotonic()
    response = _create_openai_response_with_retry(client, request_args, model_name)
    latency_ms = _elapsed_ms(started_at)
    usage = _normalize_usage(getattr(response, "usage", None), latency_ms)
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
        ],
        "usage": usage,
    })

    return AgentTurn(
        text_blocks=text_blocks,
        tool_calls=tool_calls,
        finished=len(tool_calls) == 0,
        raw_response=response,
        usage=usage,
    )


def _elapsed_ms(started_at: float) -> int:
    """
    计算模型调用耗时

    @params:
        started_at: 调用开始时的 monotonic 时间戳

    @return:
        返回毫秒级耗时，最小值为 0
    """
    return max(0, int((time.monotonic() - started_at) * 1000))


def _read_usage_value(raw_usage: Any, *names: str) -> int:
    """
    从不同 SDK usage 对象中读取 token 字段

    @params:
        raw_usage: Anthropic 或 OpenAI SDK 返回的 usage 对象
        names: 候选字段名列表

    @return:
        返回第一个可解析为整数的字段值；读取不到时返回 0
    """
    if raw_usage is None:
        return 0

    for name in names:
        if isinstance(raw_usage, dict):
            value = raw_usage.get(name)
        else:
            value = getattr(raw_usage, name, None)

        if value is None:
            continue

        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return 0


def _normalize_usage(raw_usage: Any, latency_ms: int) -> Dict[str, int]:
    """
    归一 Anthropic 与 OpenAI 的 usage 字段

    @params:
        raw_usage: SDK 响应中的 usage 对象
        latency_ms: 本轮模型调用耗时

    @return:
        返回稳定结构：prompt_tokens、completion_tokens、total_tokens、latency_ms
    """
    prompt_tokens = _read_usage_value(raw_usage, "prompt_tokens", "input_tokens")
    completion_tokens = _read_usage_value(raw_usage, "completion_tokens", "output_tokens")
    total_tokens = _read_usage_value(raw_usage, "total_tokens")
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
    }


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
            sleep_seconds = _openai_retry_delay(attempt, base_delay, max_delay, retry_after)
            _log_openai_retry("rate limited", model_name, sleep_seconds, attempt, max_retries)
            time.sleep(sleep_seconds)
        except Exception:
            if attempt >= max_retries:
                raise

            sleep_seconds = _openai_retry_delay(attempt, base_delay, max_delay)
            _log_openai_retry("request failed", model_name, sleep_seconds, attempt, max_retries)
            time.sleep(sleep_seconds)


def _openai_retry_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    retry_after: float = 0.0,
) -> float:
    """
    计算 OpenAI 重试等待时间

    @params:
        attempt: 当前重试序号，从 0 开始
        base_delay: 指数退避的基础秒数
        max_delay: 单次等待上限秒数
        retry_after: 服务端返回的建议等待秒数

    @return:
        返回本次重试前需要等待的秒数
    """
    backoff_delay = min(base_delay * (2 ** attempt), max_delay)
    return min(max(retry_after, backoff_delay), max_delay)


def _log_openai_retry(
    reason: str,
    model_name: str,
    sleep_seconds: float,
    attempt: int,
    max_retries: int,
) -> None:
    """
    输出 OpenAI 重试日志

    @params:
        reason: 重试原因
        model_name: 当前调用的模型名称
        sleep_seconds: 本次重试前等待秒数
        attempt: 当前重试序号，从 0 开始
        max_retries: 最大重试次数

    @return:
        无返回值；直接输出日志到 stdout
    """
    print(
        f"[LLM] OpenAI {reason} for model {model_name}; "
        f"retrying in {sleep_seconds:.1f}s "
        f"({attempt + 1}/{max_retries})"
    )


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
