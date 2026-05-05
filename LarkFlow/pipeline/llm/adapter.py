import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from pipeline.config import llm as llm_config
from pipeline.ops.observability import (
    log_llm_call_finished,
    log_llm_call_started,
    log_llm_retry,
)
from pipeline.llm.tools_schema import get_anthropic_tools, get_chat_completion_tools, get_openai_tools
from telemetry.otel import start_span


@dataclass
class ToolCall:
    """统一表示一条模型发起的工具调用。"""

    id: str
    name: str
    arguments: dict


@dataclass
class AgentTurn:
    """统一表示一轮模型响应，屏蔽不同 Provider 的协议差异。"""

    text_blocks: List[str]
    tool_calls: List[ToolCall]
    finished: bool
    raw_response: Any
    usage: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSpec:
    """描述某个 Provider 在 LarkFlow 中的接入契约。"""

    name: str
    build_client: Callable[[], Any]
    turn_factory: Callable[[Dict[str, Any], Any, str], AgentTurn]
    model_name_resolver: Callable[[], str]
    session_mode: str


_SESSION_MODE_MESSAGES = "messages"
_SESSION_MODE_PENDING_INPUTS = "pending_inputs"
_PROVIDER_REGISTRY: Dict[str, ProviderSpec] = {}


def _normalize_provider_name(provider: str) -> str:
    """
    把环境变量和运行时输入统一归一到小写 provider 名。

    @params:
        provider: 原始 provider 输入

    @return:
        返回去空格并转小写后的 provider 名
    """
    return (provider or "").strip().lower()


def register_provider(
    name: str,
    *,
    build_client: Callable[[], Any],
    turn_factory: Callable[[Dict[str, Any], Any, str], AgentTurn],
    model_name_resolver: Callable[[], str],
    session_mode: str,
) -> ProviderSpec:
    """
    注册一个可运行时扩展的 Provider 规格。

    @params:
        name: provider 名称，会被归一为小写后写入 registry
        build_client: 负责初始化对应 SDK client 的工厂函数
        turn_factory: 负责把该 provider 的原始响应归一成 AgentTurn
        model_name_resolver: 返回当前 provider 的模型名，用于日志和埋点
        session_mode: 会话状态模式，目前支持 messages 与 pending_inputs

    @return:
        返回写入 registry 的 ProviderSpec
    """
    normalized = _normalize_provider_name(name)
    if not normalized:
        raise ValueError("Provider name must not be empty")
    if session_mode not in {_SESSION_MODE_MESSAGES, _SESSION_MODE_PENDING_INPUTS}:
        raise ValueError(f"Unsupported session_mode: {session_mode}")

    spec = ProviderSpec(
        name=normalized,
        build_client=build_client,
        turn_factory=turn_factory,
        model_name_resolver=model_name_resolver,
        session_mode=session_mode,
    )
    _PROVIDER_REGISTRY[normalized] = spec
    return spec


def list_provider_names() -> List[str]:
    """
    返回当前 registry 中可用的 provider 名称列表。

    @params:
        无

    @return:
        返回按字典序排序后的 provider 名称列表
    """
    _ensure_provider_registry()
    return sorted(_PROVIDER_REGISTRY)


def reload_provider_registry() -> None:
    """
    重置 registry，便于测试和运行时刷新内置 Provider。

    @params:
        无

    @return:
        无返回值；会清空旧 registry 并重新注册内置 Provider
    """
    _PROVIDER_REGISTRY.clear()
    _register_builtin_providers()


def _ensure_provider_registry() -> None:
    """
    按需加载内置 Provider，避免模块导入时过早触发 SDK 依赖。

    @params:
        无

    @return:
        无返回值；当 registry 为空时完成一次延迟初始化
    """
    if not _PROVIDER_REGISTRY:
        _register_builtin_providers()


def _get_provider_spec(provider: str) -> ProviderSpec:
    """
    从 registry 中读取指定 provider 的规格定义。

    @params:
        provider: 待解析的 provider 名称，可为大小写混合输入

    @return:
        返回匹配到的 ProviderSpec；找不到时抛出 ValueError
    """
    _ensure_provider_registry()
    normalized = _normalize_provider_name(provider)
    spec = _PROVIDER_REGISTRY.get(normalized)
    if spec is None:
        supported = ", ".join(sorted(_PROVIDER_REGISTRY))
        raise ValueError(f"Unsupported LLM_PROVIDER: {normalized or provider}. Supported: {supported}")
    return spec


def get_provider_name(provider: Optional[str] = None) -> str:
    """
    读取当前配置的模型提供方，并通过 registry 校验。

    @params:
        provider: 可选显式 provider；为空时回退到环境变量 `LLM_PROVIDER`

    @return:
        返回归一化后的 provider 名称
    """
    resolved = provider if provider is not None else llm_config.provider_from_env()
    return _get_provider_spec(resolved).name


def validate_provider_name(provider: str) -> str:
    """
    校验并归一化运行时输入的 provider 名称。

    @params:
        provider: 待校验的 provider 名称

    @return:
        返回 registry 中归一化后的 provider 名称
    """
    return get_provider_name(provider)


def _require_config(value: str, message: str) -> str:
    """
    读取必填配置项，不存在时抛出可读错误。

    @params:
        value: 待校验的配置值
        message: 配置缺失时抛出的错误信息

    @return:
        返回非空配置值
    """
    if value:
        return value
    raise ValueError(message)


def build_client(provider: str) -> Any:
    """
    根据 provider 初始化对应 SDK Client。

    @params:
        provider: provider 名称

    @return:
        返回对应 SDK 的 client 实例
    """
    return _get_provider_spec(provider).build_client()


def initialize_session(provider: str, initial_user_text: str, client: Any) -> Dict[str, Any]:
    """
    初始化统一的会话状态。

    @params:
        provider: 本次需求使用的 provider
        initial_user_text: 首轮用户输入
        client: 已初始化好的 SDK client

    @return:
        返回统一的 session 字典，包含 history、provider_state 和运行时上下文
    """
    resolved_provider = get_provider_name(provider)
    # provider_state 专门保存各家 SDK 需要的协议态，history 则保留统一审计视图。
    session = {
        "provider": resolved_provider,
        "client": client,
        "history": [],
        "pending_approval": None,
        "provider_state": {},
    }
    append_user_text(session, initial_user_text)
    return session


def append_user_text(session: Dict[str, Any], text: str):
    """
    向会话中追加一条用户文本消息。

    @params:
        session: 统一会话对象
        text: 用户输入的纯文本内容

    @return:
        无返回值；会同时更新 history 与 provider_state
    """
    provider = session["provider"]
    session_mode = _get_provider_spec(provider).session_mode
    session["history"].append({"role": "user", "content": text})

    if session_mode == _SESSION_MODE_MESSAGES:
        # Anthropic / Qwen 这类 messages 协议直接沿用 role-content 结构。
        session["provider_state"].setdefault("messages", []).append({
            "role": "user",
            "content": text,
        })
    elif session_mode == _SESSION_MODE_PENDING_INPUTS:
        # Responses API 需要把本轮输入积攒到 pending_inputs，统一在 create_turn 时发送。
        session["provider_state"].setdefault("pending_inputs", []).append({
            "role": "user",
            "content": text,
        })
    else:
        raise ValueError(f"Unsupported session mode for provider {provider}: {session_mode}")


def append_tool_result(session: Dict[str, Any], tool_call: ToolCall, result_text: str):
    """
    向会话中追加一条工具执行结果。

    @params:
        session: 统一会话对象
        tool_call: 模型上一轮发出的工具调用
        result_text: 工具返回的可读文本结果

    @return:
        无返回值；会把工具结果翻译成各 Provider 可继续消费的协议格式
    """
    provider = session["provider"]
    session_mode = _get_provider_spec(provider).session_mode
    session["history"].append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": result_text,
    })

    if provider == "anthropic":
        # Anthropic 约定工具结果继续作为 user 消息里的 tool_result block 回填。
        session["provider_state"].setdefault("messages", []).append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result_text,
            }],
        })
    elif session_mode == _SESSION_MODE_PENDING_INPUTS:
        # Responses API 要求工具结果以 function_call_output 事件续接到上一条 response。
        session["provider_state"].setdefault("pending_inputs", []).append({
            "type": "function_call_output",
            "call_id": tool_call.id,
            "output": result_text,
        })
    elif session_mode == _SESSION_MODE_MESSAGES:
        session["provider_state"].setdefault("messages", []).append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.name,
            "content": result_text,
        })
    else:
        raise ValueError(f"Unsupported session mode for provider {provider}: {session_mode}")


def create_turn(session: Dict[str, Any], system_prompt: str) -> AgentTurn:
    """
    执行一轮模型调用，并返回统一后的结果。

    @params:
        session: 当前需求的统一会话状态
        system_prompt: 当前阶段的系统提示词

    @return:
        返回归一后的 AgentTurn，包含文本、工具调用、结束态和 usage
    """
    provider = session["provider"]
    client = session["client"]
    demand_id = session.get("demand_id")
    phase = session.get("phase")
    provider_spec = _get_provider_spec(provider)
    logger = session.get("logger")
    model_name = provider_spec.model_name_resolver()

    if logger:
        # create_turn 是统一入口，在这里补开始/结束日志，能覆盖所有 Provider 分支。
        log_llm_call_started(logger, phase, provider, model_name)

    with start_span(
        "llm.call",
        {
            "demand_id": demand_id,
            "phase": phase,
            "llm.provider": provider,
            "llm.model": model_name,
        },
    ) as span:
        turn = provider_spec.turn_factory(session, client, system_prompt)

        usage = turn.usage or {}
        span.set_attribute("llm.finished", turn.finished)
        span.set_attribute("llm.tool_call_count", len(turn.tool_calls))
        for key in ("latency_ms", "prompt_tokens", "completion_tokens", "total_tokens"):
            if key in usage:
                span.set_attribute(f"llm.{key}", int(usage[key] or 0))
        if logger:
            log_llm_call_finished(
                logger,
                phase,
                provider,
                model_name,
                usage,
                finished=turn.finished,
                tool_call_count=len(turn.tool_calls),
            )
        return turn


def _resolve_model_name(provider: str) -> str:
    """
    解析指定 provider 当前对应的模型名。

    @params:
        provider: provider 名称

    @return:
        返回当前 provider 的模型名
    """
    return _get_provider_spec(provider).model_name_resolver()


def _build_anthropic_client() -> Any:
    """
    构建 Anthropic SDK client。

    @params:
        无

    @return:
        返回 Anthropic client 实例
    """
    import anthropic

    api_key = llm_config.anthropic_api_key()
    base_url = llm_config.anthropic_base_url()
    return anthropic.Anthropic(api_key=api_key, base_url=base_url)


def _build_openai_client() -> Any:
    """
    构建 OpenAI SDK client。

    @params:
        无

    @return:
        返回 OpenAI client 实例
    """
    from openai import OpenAI

    api_key = llm_config.openai_api_key()
    base_url = llm_config.openai_base_url()
    return OpenAI(api_key=api_key, base_url=base_url)


def _build_qwen_client() -> Any:
    """
    构建 Qwen 兼容 OpenAI 协议的 client。

    @params:
        无

    @return:
        返回 OpenAI 兼容 client 实例
    """
    from openai import OpenAI

    api_key = llm_config.qwen_api_key()
    base_url = llm_config.qwen_base_url()
    return OpenAI(api_key=api_key, base_url=base_url)


def _build_doubao_client() -> Any:
    """
    构建 Doubao / ARK 的 OpenAI 兼容 client。

    @params:
        无

    @return:
        返回 OpenAI 兼容 client 实例；缺少 API Key 时抛出错误
    """
    from openai import OpenAI

    api_key = _require_config(
        llm_config.doubao_api_key(),
        "Doubao API key is not configured; set DOUBAO_API_KEY or ARK_API_KEY",
    )
    base_url = llm_config.doubao_base_url()
    return OpenAI(api_key=api_key, base_url=base_url)


def _resolve_anthropic_model_name() -> str:
    """
    解析 Anthropic 当前模型名。

    @params:
        无

    @return:
        返回环境变量中的模型名；为空时回退默认值
    """
    return llm_config.anthropic_model()


def _resolve_openai_model_name() -> str:
    """
    解析 OpenAI 当前模型名。

    @params:
        无

    @return:
        返回环境变量中的模型名；为空时回退默认值
    """
    return llm_config.openai_model()


def _resolve_qwen_model_name() -> str:
    """
    解析 Qwen 当前模型名。

    @params:
        无

    @return:
        按优先级返回 QWEN / DASHSCOPE 模型名
    """
    return llm_config.qwen_resolver_model()


def _resolve_doubao_model_name() -> str:
    """
    解析 Doubao 当前模型名或 endpoint ID。

    @params:
        无

    @return:
        按优先级返回 DOUBAO / ARK 模型配置
    """
    return llm_config.doubao_model()


def _create_anthropic_turn(session: Dict[str, Any], client: Any, system_prompt: str) -> AgentTurn:
    """
    执行一轮 Anthropic Messages API 调用。

    @params:
        session: 当前统一会话状态
        client: Anthropic SDK client
        system_prompt: 当前阶段系统提示词

    @return:
        返回归一后的 AgentTurn
    """
    messages = session["provider_state"].setdefault("messages", [])
    model_name = llm_config.anthropic_model()

    started_at = time.monotonic()
    response = client.messages.create(
        model=model_name,
        max_tokens=12288,
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
    """
    执行一轮 OpenAI Responses API 调用。

    @params:
        session: 当前统一会话状态
        client: OpenAI SDK client
        system_prompt: 当前阶段系统提示词

    @return:
        返回归一后的 AgentTurn
    """
    return _create_responses_turn(
        session,
        client,
        system_prompt,
        provider_label="OpenAI",
        model_env_names=llm_config.openai_model_env_names(),
        default_model=llm_config.DEFAULT_OPENAI_MODEL,
        retry_env_prefix=llm_config.openai_retry_env_prefix(),
        reasoning_env_name=llm_config.openai_reasoning_env_name(),
    )


def _create_doubao_turn(session: Dict[str, Any], client: Any, system_prompt: str) -> AgentTurn:
    """
    执行一轮 Doubao/ARK Responses API 调用。

    @params:
        session: 当前统一会话状态
        client: OpenAI 兼容 client
        system_prompt: 当前阶段系统提示词

    @return:
        返回归一后的 AgentTurn
    """
    return _create_responses_turn(
        session,
        client,
        system_prompt,
        provider_label="Doubao",
        model_env_names=llm_config.doubao_model_env_names(),
        default_model="",
        retry_env_prefix=llm_config.doubao_retry_env_prefix(),
        reasoning_env_name="",
    )


def _create_responses_turn(
    session: Dict[str, Any],
    client: Any,
    system_prompt: str,
    provider_label: str,
    model_env_names: List[str],
    default_model: str,
    retry_env_prefix: str,
    reasoning_env_name: str,
) -> AgentTurn:
    """
    执行基于 OpenAI Responses API 协议的一轮调用。

    @params:
        session: 当前统一会话状态
        client: 对应 Provider 的 SDK client
        system_prompt: 当前阶段系统提示词
        provider_label: 仅用于错误信息和日志展示
        model_env_names: 按优先级读取模型名的环境变量列表
        default_model: 所有环境变量都为空时的默认模型名
        retry_env_prefix: 重试相关环境变量前缀
        reasoning_env_name: 可选的 reasoning effort 配置名；为空时表示该 Provider 不使用该参数

    @return:
        返回归一后的 AgentTurn
    """
    state = session["provider_state"]
    pending_inputs = list(state.get("pending_inputs", []))
    model_name = _first_env_value(model_env_names, default_model)
    logger = session.get("logger")
    phase = session.get("phase")
    if not model_name:
        raise ValueError(
            f"{provider_label} model is not configured; set one of: {', '.join(model_env_names)}"
        )

    previous_response_id = state.get("previous_response_id")
    if session.get("provider") == "doubao" and previous_response_id and not pending_inputs:
        # Ark Responses rejects empty input on continuation turns, while OpenAI accepts it.
        pending_inputs = [{
            "role": "user",
            "content": "继续执行当前阶段；如果已经完成，请直接给出最终结果。",
        }]

    # Responses API 采用 previous_response_id 续接同一条响应链，工具调用和多轮对话都依赖这个链路。
    request_args = {
        "model": model_name,
        "instructions": system_prompt,
        "input": pending_inputs,
        "tools": get_openai_tools(),
        "max_output_tokens": 12288,
    }

    if reasoning_env_name and _model_supports_reasoning(model_name):
        reasoning_effort = llm_config.reasoning_effort(reasoning_env_name)
        if reasoning_effort:
            request_args["reasoning"] = {"effort": reasoning_effort}

    if previous_response_id:
        request_args["previous_response_id"] = previous_response_id

    started_at = time.monotonic()
    response = _create_responses_response_with_retry(
        client,
        request_args,
        provider_label,
        retry_env_prefix,
        model_name,
        logger=logger,
        phase=phase,
    )
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


def _first_env_value(names: List[str], default: str = "") -> str:
    """
    按优先级读取第一项非空环境变量。

    @params:
        names: 环境变量名列表
        default: 所有环境变量都为空时的默认值

    @return:
        返回第一个非空值；全部为空时返回 default
    """
    return llm_config.first_env_value(names, default)


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


def _create_qwen_turn(session: Dict[str, Any], client: Any, system_prompt: str) -> AgentTurn:
    """
    执行一轮 Qwen Chat Completions 调用。

    @params:
        session: 当前统一会话状态
        client: Qwen 兼容 OpenAI 协议的 client
        system_prompt: 当前阶段系统提示词

    @return:
        返回归一后的 AgentTurn
    """
    state = session["provider_state"]
    messages = state.setdefault("messages", [])
    model_name = llm_config.qwen_turn_model()

    started_at = time.monotonic()
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        tools=get_chat_completion_tools(),
        tool_choice="auto",
    )
    latency_ms = _elapsed_ms(started_at)
    usage = _normalize_usage(getattr(response, "usage", None), latency_ms)

    choice = response.choices[0]
    message = choice.message
    assistant_message = {
        "role": "assistant",
        "content": message.content or "",
    }

    tool_calls = []
    if message.tool_calls:
        # Qwen 兼容 Chat Completions 协议，工具调用需要保留 function 结构以便下一轮 tool 消息续接。
        assistant_message["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
        for tool_call in message.tool_calls:
            tool_calls.append(ToolCall(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments=_safe_json_loads(tool_call.function.arguments or "{}"),
            ))

    messages.append(assistant_message)

    text_blocks = [message.content] if message.content else []
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


def _model_supports_reasoning(model_name: str) -> bool:
    """
    判断模型是否支持 reasoning 参数。

    @params:
        model_name: 待判断的模型名

    @return:
        支持时返回 True，否则返回 False
    """
    name = (model_name or "").lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _create_openai_response_with_retry(client: Any, request_args: Dict[str, Any], model_name: str) -> Any:
    """
    兼容旧调用入口，执行 OpenAI Responses API 重试逻辑。

    @params:
        client: OpenAI SDK client
        request_args: 传给 responses.create 的请求参数
        model_name: 本次调用模型名

    @return:
        返回 SDK 的原始 response 对象
    """
    return _create_responses_response_with_retry(
        client,
        request_args,
        provider_label="OpenAI",
        env_prefix="OPENAI",
        model_name=model_name,
    )


def _create_responses_response_with_retry(
    client: Any,
    request_args: Dict[str, Any],
    provider_label: str,
    env_prefix: str,
    model_name: str,
    logger: Any = None,
    phase: Optional[str] = None,
) -> Any:
    """
    调用 Responses API，并对限流与瞬时错误做统一重试。

    @params:
        client: OpenAI 兼容 client
        request_args: 传给 responses.create 的请求参数
        provider_label: Provider 名称，仅用于报错信息
        env_prefix: 重试配置环境变量前缀
        model_name: 本次调用模型名
        logger: 可选结构化 logger；传入后重试事件会写入 JSON 日志
        phase: 可选阶段名；仅在写结构化重试日志时使用

    @return:
        返回 SDK 的原始 response 对象
    """
    from openai import RateLimitError

    max_retries = llm_config.retry_max_retries(env_prefix)
    base_delay = llm_config.retry_base_seconds(env_prefix)
    max_delay = llm_config.retry_max_seconds(env_prefix)

    for attempt in range(max_retries + 1):
        try:
            return client.responses.create(**request_args)
        except RateLimitError as exc:
            if attempt >= max_retries:
                raise

            retry_after = _extract_retry_after_seconds(str(exc))
            sleep_seconds = _openai_retry_delay(attempt, base_delay, max_delay, retry_after)
            _log_responses_retry(
                provider_label,
                "rate limited",
                model_name,
                sleep_seconds,
                attempt,
                max_retries,
                logger=logger,
                phase=phase,
            )
            time.sleep(sleep_seconds)
        except Exception:
            if attempt >= max_retries:
                raise

            sleep_seconds = _openai_retry_delay(attempt, base_delay, max_delay)
            _log_responses_retry(
                provider_label,
                "request failed",
                model_name,
                sleep_seconds,
                attempt,
                max_retries,
                logger=logger,
                phase=phase,
            )
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


def _log_responses_retry(
    provider_label: str,
    reason: str,
    model_name: str,
    sleep_seconds: float,
    attempt: int,
    max_retries: int,
    logger: Any = None,
    phase: Optional[str] = None,
) -> None:
    """
    输出 OpenAI 重试日志

    @params:
        provider_label: Provider 展示名
        reason: 重试原因
        model_name: 当前调用的模型名称
        sleep_seconds: 本次重试前等待秒数
        attempt: 当前重试序号，从 0 开始
        max_retries: 最大重试次数
        logger: 可选结构化 logger；为空时回退到 stdout
        phase: 可选阶段名；仅在结构化日志分支中使用

    @return:
        无返回值；直接输出结构化日志或 stdout 文本
    """
    if logger:
        # 运行在 engine 主链路时优先走结构化 logger，便于 Loki 按 phase / provider / event 检索。
        log_llm_retry(
            logger,
            phase,
            provider_label.lower(),
            model_name,
            reason,
            attempt=attempt + 1,
            max_retries=max_retries,
            wait_seconds=sleep_seconds,
        )
        return

    print(
        f"[LLM] {provider_label} {reason} for model {model_name}; "
        f"retrying in {sleep_seconds:.1f}s "
        f"({attempt + 1}/{max_retries})"
    )


def _extract_openai_message_text(message: Any) -> List[str]:
    """
    从 OpenAI Responses message 中提取可读文本块。

    @params:
        message: Responses API 返回的 message 项

    @return:
        返回按顺序提取出的文本块列表
    """
    texts = []
    for content_item in getattr(message, "content", []):
        content_type = getattr(content_item, "type", "")
        if content_type in {"output_text", "text"}:
            text_value = getattr(content_item, "text", "")
            if text_value:
                texts.append(text_value)
    return texts


def _safe_json_loads(raw: str) -> dict:
    """
    尝试把工具参数字符串解析为 JSON。

    @params:
        raw: 模型返回的原始 arguments 字符串

    @return:
        解析成功时返回字典；失败时返回带 `raw_arguments` 的兜底结构
    """
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        return {"raw_arguments": raw}


def _extract_retry_after_seconds(error_text: str) -> float:
    """
    从限流错误文案中提取服务端建议的等待秒数。

    @params:
        error_text: OpenAI SDK 抛出的错误文本

    @return:
        提取成功时返回秒数；没有匹配到时返回 0
    """
    match = re.search(r"Please try again in ([0-9.]+)s", error_text)
    if not match:
        return 0.0

    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _register_builtin_providers() -> None:
    """
    注册仓库内置支持的 Provider。

    @params:
        无

    @return:
        无返回值；直接把内置 Provider 写入全局 registry
    """
    register_provider(
        "anthropic",
        build_client=_build_anthropic_client,
        turn_factory=_create_anthropic_turn,
        model_name_resolver=_resolve_anthropic_model_name,
        session_mode=_SESSION_MODE_MESSAGES,
    )
    register_provider(
        "openai",
        build_client=_build_openai_client,
        turn_factory=_create_openai_turn,
        model_name_resolver=_resolve_openai_model_name,
        session_mode=_SESSION_MODE_PENDING_INPUTS,
    )
    register_provider(
        "qwen",
        build_client=_build_qwen_client,
        turn_factory=_create_qwen_turn,
        model_name_resolver=_resolve_qwen_model_name,
        session_mode=_SESSION_MODE_MESSAGES,
    )
    register_provider(
        "doubao",
        build_client=_build_doubao_client,
        turn_factory=_create_doubao_turn,
        model_name_resolver=_resolve_doubao_model_name,
        session_mode=_SESSION_MODE_PENDING_INPUTS,
    )


reload_provider_registry()
