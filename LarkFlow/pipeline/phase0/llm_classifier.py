"""Phase 0 LLM 分类器：用小模型把 NL 需求抽成结构化 NormalizedDemand。

设计：
- 只在显式开启 (`LARKFLOW_PHASE0_LLM_ENABLED`) 时生效；默认走规则版。
- 调 OpenAI 兼容 API（同 `pipeline/skills/semantic.py` 的做法，支持 Doubao/Qwen/OpenAI）。
- LLM 输出严格 JSON，若 parse 失败或字段缺失 → 自动回落规则版。
- 输出与规则版合并（hybrid）：以 LLM 为主，用规则版补兜底字段。
- `confidence` 由 LLM 输出；缺字段时按启发式扣分。
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import replace
from typing import Any, Callable, Optional

from pipeline.phase0.schema import (
    ApiSketch,
    NfrFlags,
    NormalizedDemand,
    OpenQuestion,
    PersistenceHint,
)

_LOG = logging.getLogger("larkflow.phase0.llm")

_ENV_ENABLED = "LARKFLOW_PHASE0_LLM_ENABLED"
_ENV_MODEL = "LARKFLOW_PHASE0_MODEL"
_ENV_API_KEY = "LARKFLOW_PHASE0_API_KEY"
_ENV_BASE_URL = "LARKFLOW_PHASE0_BASE_URL"
_ENV_CONFIDENCE_FLOOR = "LARKFLOW_PHASE0_CONFIDENCE_FLOOR"

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_CONFIDENCE_FLOOR = 0.75

# LLM 最多跑一次；JSON 解析失败直接降级，不自作主张 retry 省 token
_SYSTEM_PROMPT = """You are a demand normalizer for a Kratos Go microservice pipeline.
Given a natural-language requirement, extract a structured summary that a senior engineer
would agree with. Respond with STRICT JSON ONLY, no code fences, no prose.

Fields (all required, empty list/false/"" when unknown):
- goal:                  one-sentence summary of what ships
- out_of_scope:          array of strings the author explicitly excluded
- entities:              domain entities (e.g. ["Order", "Refund"])
- apis:                  [{method: "GET|POST|PUT|PATCH|DELETE|gRPC|", path: "", purpose: ""}]
- persistence:           {needs_storage: bool, needs_migration: bool, tables: [str], notes: str}
- nfr:                   {auth: bool, idempotent: bool, rate_limit: bool, transactional: bool, high_concurrency: bool}
- domain_tags:           subset of ["order","user","payment"] that applies, else []
- touches_python:        true only if the change is in the LarkFlow control plane (pipeline/, tests/)
- open_questions:        [{text: str, blocking: bool, candidates: [str]}]
                         blocking=true only when the answer materially changes the API contract or data model
- confidence:            float in [0,1]; lower when the demand is vague or self-contradictory
"""

_USER_TEMPLATE = "Requirement:\n{requirement}\n\nReturn the JSON now."


LLMCallFn = Callable[[str, str, str], str]
"""模拟签名：(system_prompt, user_prompt, model) -> raw_json_string"""


def is_enabled() -> bool:
    """env 开关：默认关闭（规则版优先，LLM 作为可选增强）。"""
    val = os.getenv(_ENV_ENABLED, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def confidence_floor() -> float:
    """低于此置信度 → 触发澄清回路。"""
    raw = os.getenv(_ENV_CONFIDENCE_FLOOR, "").strip()
    if not raw:
        return _DEFAULT_CONFIDENCE_FLOOR
    try:
        val = float(raw)
    except ValueError:
        return _DEFAULT_CONFIDENCE_FLOOR
    if not 0.0 <= val <= 1.0:
        return _DEFAULT_CONFIDENCE_FLOOR
    return val


def _build_openai_call() -> Optional[LLMCallFn]:
    """构造一个 OpenAI 兼容的 chat-completions 调用；缺 key 或 SDK 时返回 None。"""
    api_key = os.getenv(_ENV_API_KEY) or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = (
        os.getenv(_ENV_BASE_URL)
        or os.getenv("OPENAI_BASE_URL")
        or None
    )
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        _LOG.warning("openai SDK not installed; phase0 LLM falls back to rule-only")
        return None
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    def _call(system_prompt: str, user_prompt: str, model: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return _call


def _resolve_call_fn(override: Optional[LLMCallFn]) -> Optional[LLMCallFn]:
    if override is not None:
        return override
    return _build_openai_call()


_JSON_FALLBACK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _safe_parse_json(raw: str) -> Optional[dict[str, Any]]:
    """宽松解析 LLM JSON：先直接 parse，失败尝试抽第一个 `{...}` 块。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = _JSON_FALLBACK_RE.search(raw)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def _coerce_str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _parse_apis(raw: Any) -> list[ApiSketch]:
    if not isinstance(raw, list):
        return []
    out: list[ApiSketch] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            ApiSketch(
                method=str(item.get("method", "") or "").upper(),
                path=str(item.get("path", "") or ""),
                purpose=str(item.get("purpose", "") or ""),
            )
        )
    return out


def _parse_persistence(raw: Any) -> PersistenceHint:
    if not isinstance(raw, dict):
        return PersistenceHint()
    return PersistenceHint(
        needs_storage=_coerce_bool(raw.get("needs_storage")),
        needs_migration=_coerce_bool(raw.get("needs_migration")),
        tables=_coerce_str_list(raw.get("tables")),
        notes=str(raw.get("notes", "") or ""),
    )


def _parse_nfr(raw: Any) -> NfrFlags:
    if not isinstance(raw, dict):
        return NfrFlags()
    return NfrFlags(
        auth=_coerce_bool(raw.get("auth")),
        idempotent=_coerce_bool(raw.get("idempotent")),
        rate_limit=_coerce_bool(raw.get("rate_limit")),
        transactional=_coerce_bool(raw.get("transactional")),
        high_concurrency=_coerce_bool(raw.get("high_concurrency")),
    )


def _parse_open_questions(raw: Any) -> list[OpenQuestion]:
    if not isinstance(raw, list):
        return []
    out: list[OpenQuestion] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        out.append(
            OpenQuestion(
                text=text,
                blocking=_coerce_bool(item.get("blocking")),
                candidates=_coerce_str_list(item.get("candidates")),
            )
        )
    return out


def _parse_confidence(raw: Any) -> float:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.6
    return max(0.0, min(1.0, val))


def _parse_payload(
    raw_demand: str,
    payload: dict[str, Any],
) -> NormalizedDemand:
    return NormalizedDemand(
        raw_demand=raw_demand,
        goal=str(payload.get("goal", "") or "").strip(),
        out_of_scope=_coerce_str_list(payload.get("out_of_scope")),
        entities=_coerce_str_list(payload.get("entities")),
        apis=_parse_apis(payload.get("apis")),
        persistence=_parse_persistence(payload.get("persistence")),
        nfr=_parse_nfr(payload.get("nfr")),
        domain_tags=_coerce_str_list(payload.get("domain_tags")),
        touches_python=_coerce_bool(payload.get("touches_python")),
        open_questions=_parse_open_questions(payload.get("open_questions")),
        confidence=_parse_confidence(payload.get("confidence")),
        source="llm",
    )


def _merge_with_rule(llm: NormalizedDemand, rule: NormalizedDemand) -> NormalizedDemand:
    """把规则版当兜底，LLM 缺字段时补上；同时把 source 标成 hybrid。"""
    goal = llm.goal or rule.goal
    entities = llm.entities or rule.entities
    apis = llm.apis or rule.apis
    persistence = llm.persistence
    if not any(
        [
            persistence.needs_storage,
            persistence.needs_migration,
            persistence.tables,
            persistence.notes,
        ]
    ):
        persistence = rule.persistence
    nfr = llm.nfr
    if not any(
        [nfr.auth, nfr.idempotent, nfr.rate_limit, nfr.transactional, nfr.high_concurrency]
    ):
        nfr = rule.nfr
    domain_tags = llm.domain_tags or rule.domain_tags
    touches_python = llm.touches_python or rule.touches_python
    # open_questions 取并集，按 blocking 优先
    merged_qs: list[OpenQuestion] = list(llm.open_questions)
    seen_text = {q.text for q in merged_qs}
    for q in rule.open_questions:
        if q.text not in seen_text:
            merged_qs.append(q)
            seen_text.add(q.text)
    return replace(
        llm,
        goal=goal,
        entities=entities,
        apis=apis,
        persistence=persistence,
        nfr=nfr,
        domain_tags=domain_tags,
        touches_python=touches_python,
        open_questions=merged_qs,
        source="hybrid",
    )


def classify(
    raw_demand: str,
    *,
    rule_fallback: NormalizedDemand,
    call_fn: Optional[LLMCallFn] = None,
    model: Optional[str] = None,
) -> NormalizedDemand:
    """调 LLM 分类并与规则版合并。

    @params:
        raw_demand   : 原始自然语言需求
        rule_fallback: 规则版的结果，用作兜底与合并基底
        call_fn      : 可注入的 LLM 调用函数；None 时按 env 构造 OpenAI 客户端
        model        : 覆盖模型名；None 时读 env
    @return:
        合并后的 NormalizedDemand；LLM 失败/关闭 → 直接返回 rule_fallback。
    """
    if not (raw_demand or "").strip():
        return rule_fallback
    fn = _resolve_call_fn(call_fn)
    if fn is None:
        return rule_fallback
    resolved_model = model or os.getenv(_ENV_MODEL, _DEFAULT_MODEL)
    try:
        raw = fn(_SYSTEM_PROMPT, _USER_TEMPLATE.format(requirement=raw_demand), resolved_model)
    except Exception as exc:  # noqa: BLE001 — 任何异常都降级
        _LOG.warning("phase0 LLM call failed, using rule fallback: %s", exc)
        return rule_fallback
    payload = _safe_parse_json(raw)
    if not payload:
        _LOG.warning("phase0 LLM produced non-JSON output, using rule fallback")
        return rule_fallback
    llm_demand = _parse_payload(raw_demand, payload)
    # LLM 说啥都不信它不给 goal；goal 缺失 → 整条扔掉用规则版
    if not llm_demand.goal:
        return rule_fallback
    return _merge_with_rule(llm_demand, rule_fallback)
