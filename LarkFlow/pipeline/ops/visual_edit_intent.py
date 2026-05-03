"""
视觉编辑意图归一化。

把用户在圈选面板里的自然语言输入转换成后端可执行的结构化动作。
优先尝试 LLM 意图理解；若 LLM 不可用或结果非法，再回退到规则解析。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pipeline.core.contracts import VisualEditContextNode, VisualEditTarget
from pipeline.llm.adapter import build_client, create_turn, get_provider_name, initialize_session


VisualEditActionKind = Literal["replace_text", "set_style"]
VisualEditActionSource = Literal["rule", "llm"]


class VisualEditIntentError(ValueError):
    """Raised when a user intent cannot be normalized safely."""


@dataclass(frozen=True)
class VisualEditAction:
    kind: VisualEditActionKind
    value: str
    property_name: str | None = None
    confidence: float = 1.0
    source: VisualEditActionSource = "rule"


COLOR_ALIASES = {
    "蓝色": "#3b82f6",
    "浅蓝色": "#60a5fa",
    "深蓝色": "#1d4ed8",
    "红色": "#ef4444",
    "粉色": "#ec4899",
    "浅粉色": "#f9a8d4",
    "深粉色": "#db2777",
    "橙色": "#f97316",
    "绿色": "#22c55e",
    "黄色": "#eab308",
    "紫色": "#8b5cf6",
    "黑色": "#111827",
    "白色": "#ffffff",
    "灰色": "#6b7280",
}
ALLOWED_STYLE_PROPERTIES = {
    "color",
    "backgroundColor",
    "borderColor",
    "borderWidth",
    "borderRadius",
    "fontSize",
    "fontWeight",
    "padding",
    "margin",
}
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
_RGB_COLOR_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
_PX_VALUE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*px")
_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)")
_TRAILING_TEXT_NOISE_RE = re.compile(r"(?:吧|一下|一点|一些)$")
_TEXT_PATTERNS = (
    re.compile(r'(?:把|将|请)?\s*(?:这里|这个|这段|文字|文案|标题|按钮文案)?\s*(?:改成|改为|换成|替换成|显示为|显示成|叫)\s*[“"](.+?)[”"]\s*[。.]?$'),
    re.compile(r'(?:把|将|请)?\s*(?:这里|这个|这段|文字|文案|标题|按钮文案)?\s*(?:改成|改为|换成|替换成|显示为|显示成|叫)\s+(.+?)\s*[。.]?$'),
    re.compile(r'(?:改成|改为|换成|替换成|显示为|显示成|叫)\s*(.+?)\s*[。.]?$'),
    re.compile(r'(?:把|将|请)?\s*(?:文字|文案|标题|按钮文案)\s*(?:改成|改为|换成|替换成|显示为|显示成|叫)\s*(.+?)\s*[。.]?$'),
)


def resolve_visual_edit_action(
    *,
    intent: str,
    target: VisualEditTarget,
    enable_llm: bool = True,
) -> VisualEditAction:
    """
    把用户意图转换成结构化视觉编辑动作。

    @params:
        intent: 用户原始修改意图
        target: 圈选元素上下文
        enable_llm: 是否允许调用 LLM 做首轮意图理解

    @return:
        返回可执行的 VisualEditAction
    """
    normalized = _normalize_intent(intent)
    if not normalized:
        raise VisualEditIntentError("请输入修改意图。")

    if enable_llm:
        try:
            return _resolve_by_llm(normalized, target)
        except VisualEditIntentError:
            pass

    rule_action = _resolve_by_rules(normalized, target)
    if rule_action:
        return rule_action

    if enable_llm:
        raise VisualEditIntentError("没有理解这次修改意图，请换一种说法。")
    raise VisualEditIntentError("没有理解这次修改意图，请换一种说法。")


def _normalize_intent(intent: str) -> str:
    return re.sub(r"\s+", " ", (intent or "").strip())


def _resolve_by_rules(intent: str, target: VisualEditTarget) -> VisualEditAction | None:
    referenced_color = _extract_contextual_color(intent, target)
    if referenced_color:
        return VisualEditAction(
            kind="set_style",
            value=referenced_color,
            property_name=_choose_color_property(target, intent),
            source="rule",
        )

    color = _extract_color(intent)
    if color:
        return VisualEditAction(
            kind="set_style",
            value=color,
            property_name=_choose_color_property(target, intent),
            source="rule",
        )

    style_action = _extract_style_action(intent, target)
    if style_action:
        return style_action

    text = _extract_text(intent)
    if text:
        return VisualEditAction(kind="replace_text", value=text, source="rule")
    return None


def _extract_style_action(intent: str, target: VisualEditTarget) -> VisualEditAction | None:
    property_name = _infer_style_property(intent, target)
    if not property_name:
        return None

    normalized = _normalize_style_value(property_name, intent)
    if not normalized:
        return None

    return VisualEditAction(
        kind="set_style",
        value=normalized,
        property_name=property_name,
        source="rule",
    )


def _extract_contextual_color(intent: str, target: VisualEditTarget) -> str | None:
    if not any(word in intent for word in ("一样", "一致", "相同")):
        return None
    if not any(word in intent for word in ("颜色", "色", "字体", "文字", "文本", "标题")):
        return None

    if target.reference:
        referenced = _extract_color(target.reference.style.color or "")
        if referenced:
            return referenced

    context = getattr(target, "context", None)
    if not context:
        return None

    ref_node: VisualEditContextNode | None = None
    if "后面" in intent:
        ref_node = context.next
    elif "前面" in intent:
        ref_node = context.previous
    elif "父" in intent or "上层" in intent:
        ref_node = context.parent

    if not ref_node:
        return None
    return _extract_color(ref_node.style.color or "")


def _extract_color(intent: str) -> str | None:
    direct = _HEX_COLOR_RE.search(intent)
    if direct:
        return direct.group(0)

    rgb_match = _RGB_COLOR_RE.search(intent)
    if rgb_match:
        red, green, blue = (max(0, min(255, int(value))) for value in rgb_match.groups())
        return f"#{red:02x}{green:02x}{blue:02x}"

    has_color_action = any(word in intent for word in ("颜色", "改成", "改为", "换成", "变成", "调成", "设为"))
    for name, value in COLOR_ALIASES.items():
        if name in intent and has_color_action:
            return value
    return None


def _extract_text(intent: str) -> str | None:
    for pattern in _TEXT_PATTERNS:
        match = pattern.search(intent)
        if not match:
            continue
        value = _clean_text_value(match.group(1))
        if value:
            return value
    return None


def _clean_text_value(value: str) -> str:
    cleaned = (value or "").strip().strip("。").strip('“”"')
    cleaned = _TRAILING_TEXT_NOISE_RE.sub("", cleaned).strip()
    return cleaned


def _choose_color_property(target: VisualEditTarget, intent: str) -> str:
    class_name = (target.class_name or "").lower()
    tag = (target.tag or "").lower()
    if any(word in intent for word in ("字体", "文字", "文本", "标题", "字色", "文字颜色", "字体颜色")):
        return "color"
    if "背景" in intent or "按钮" in intent or "button" in class_name or tag in {"button", "a"}:
        return "backgroundColor"
    return "color"


def _infer_style_property(intent: str, target: VisualEditTarget) -> str | None:
    if any(word in intent for word in ("边框颜色", "描边颜色")):
        return "borderColor"
    if any(word in intent for word in ("边框", "描边")) and any(word in intent for word in ("粗", "细", "宽", "px", "像素")):
        return "borderWidth"
    if any(word in intent for word in ("圆角", "更圆", "圆润")):
        return "borderRadius"
    if any(word in intent for word in ("字号", "字大", "字小", "字体大小", "文字大小")):
        return "fontSize"
    if any(word in intent for word in ("加粗", "变粗", "更粗", "细一点", "字重")):
        return "fontWeight"
    if "内边距" in intent:
        return "padding"
    if "外边距" in intent:
        return "margin"
    if any(word in intent for word in ("背景", "按钮")):
        color = _extract_color(intent)
        if color:
            return "backgroundColor"
    return None


def _normalize_style_value(property_name: str, intent: str) -> str | None:
    if property_name in {"color", "backgroundColor", "borderColor"}:
        return _extract_color(intent)

    if property_name in {"borderWidth", "borderRadius", "fontSize", "padding", "margin"}:
        match = _PX_VALUE_RE.search(intent) or _NUMBER_RE.search(intent)
        if match:
            return f"{match.group(1)}px"
        if property_name == "borderWidth":
            if "粗一点" in intent or "更粗" in intent:
                return "2px"
            if "细一点" in intent or "更细" in intent:
                return "1px"
        if property_name == "borderRadius":
            if "更圆" in intent or "圆润" in intent:
                return "16px"
        if property_name == "fontSize":
            if "大一点" in intent or "更大" in intent:
                return "18px"
            if "小一点" in intent or "更小" in intent:
                return "14px"
        return None

    if property_name == "fontWeight":
        if any(word in intent for word in ("加粗", "更粗", "变粗")):
            return "700"
        if any(word in intent for word in ("细一点", "更细")):
            return "400"
        number_match = _NUMBER_RE.search(intent)
        if number_match:
            return number_match.group(1)
        return None

    return None


def _resolve_by_llm(intent: str, target: VisualEditTarget) -> VisualEditAction:
    prompt = _build_llm_prompt(intent, target)
    try:
        provider = get_provider_name()
        client = build_client(provider)
        session = initialize_session(provider, prompt, client)
        session["phase"] = "visual_edit_intent"
        turn = create_turn(session, _SYSTEM_PROMPT)
    except Exception as exc:  # noqa: BLE001
        raise VisualEditIntentError(f"LLM 意图理解不可用：{exc}") from exc

    raw_text = "\n".join(turn.text_blocks).strip()
    payload = _parse_json_payload(raw_text)
    return _validate_llm_action(payload, target)


_SYSTEM_PROMPT = """
You normalize visual editing instructions for a frontend page.
Return JSON only. Do not use markdown.

Allowed actions:
1. replace_text: replace the selected visible text with a new text.
2. set_style: update a single inline style property on the selected element.

Output schema:
{
  "kind": "replace_text" | "set_style",
  "value": "final text or css value",
  "property_name": "color" | "backgroundColor" | "borderColor" | "borderWidth" | "borderRadius" | "fontSize" | "fontWeight" | "padding" | "margin" | null,
  "confidence": 0.0-1.0
}

Rules:
- Prefer replace_text for copywriting instructions.
- For colors, return a hex color.
- For style edits, pick exactly one property and one final value.
- For border/font/spacing requests, return a valid CSS value such as "2px", "16px", or "700".
- For button/background targets, use backgroundColor when the user refers to background/button color.
- For title/paragraph text targets, use color when the user refers to text/font color.
- Keep copy concise and faithful to the user's intent.
""".strip()


def _build_llm_prompt(intent: str, target: VisualEditTarget) -> str:
    return json.dumps(
        {
            "user_intent": intent,
            "selected_element": {
                "tag": target.tag,
                "class_name": target.class_name,
                "text": target.text,
                "css_selector": target.css_selector,
                "lark_src": target.lark_src,
                "context": {
                    "previous": _dump_context_node(target.context.previous) if target.context and target.context.previous else None,
                    "next": _dump_context_node(target.context.next) if target.context and target.context.next else None,
                    "parent": _dump_context_node(target.context.parent) if target.context and target.context.parent else None,
                },
                "reference": _dump_context_node(target.reference) if target.reference else None,
            },
        },
        ensure_ascii=False,
    )


def _dump_context_node(node: VisualEditContextNode) -> dict:
    return {
        "relation": node.relation,
        "tag": node.tag,
        "text": node.text,
        "css_selector": node.css_selector,
        "class_name": node.class_name,
        "style": {
            "color": node.style.color,
            "backgroundColor": node.style.backgroundColor,
            "fontSize": node.style.fontSize,
            "fontWeight": node.style.fontWeight,
        },
    }


def _parse_json_payload(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisualEditIntentError("LLM 意图理解结果不是有效 JSON。") from exc
    if not isinstance(payload, dict):
        raise VisualEditIntentError("LLM 意图理解结果格式无效。")
    return payload


def _validate_llm_action(payload: dict, target: VisualEditTarget) -> VisualEditAction:
    kind = payload.get("kind")
    value = str(payload.get("value") or "").strip()
    property_name = payload.get("property_name")
    confidence = float(payload.get("confidence") or 0.0)

    if kind == "replace_text":
        text = _clean_text_value(value)
        if not text:
            raise VisualEditIntentError("LLM 未生成可替换文案。")
        return VisualEditAction(
            kind="replace_text",
            value=text,
            confidence=confidence,
            source="llm",
        )

    if kind == "set_style":
        prop = property_name if property_name in ALLOWED_STYLE_PROPERTIES else None
        if not prop:
            raise VisualEditIntentError("LLM 生成了不支持的样式属性。")
        normalized = _normalize_llm_style_value(prop, value, target)
        if not normalized:
            raise VisualEditIntentError("LLM 未生成有效样式值。")
        return VisualEditAction(
            kind="set_style",
            value=normalized,
            property_name=prop,
            confidence=confidence,
            source="llm",
        )

    raise VisualEditIntentError("LLM 生成了不支持的视觉编辑动作。")


def _normalize_llm_style_value(property_name: str, value: str, target: VisualEditTarget) -> str | None:
    normalized_value = (value or "").strip()
    if property_name in {"color", "backgroundColor", "borderColor"}:
        return _extract_color(normalized_value) or None

    if property_name in {"borderWidth", "borderRadius", "fontSize", "padding", "margin"}:
        px_match = _PX_VALUE_RE.search(normalized_value) or _NUMBER_RE.search(normalized_value)
        if not px_match:
            return None
        return f"{px_match.group(1)}px"

    if property_name == "fontWeight":
        if normalized_value in {"normal", "bold"}:
            return "400" if normalized_value == "normal" else "700"
        number_match = _NUMBER_RE.search(normalized_value)
        if number_match:
            return number_match.group(1)
        if any(word in normalized_value for word in ("粗", "bold")):
            return "700"
        if any(word in normalized_value for word in ("细", "normal")):
            return "400"
        return None

    return None
