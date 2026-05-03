"""飞书审批卡片模板（双 HITL）。

统一两张卡片的 JSON 结构，按钮 value 一致携带 {checkpoint, action, demand_id}，
供 `lark_interaction.process_card_action` 按 checkpoint 分发到对应 engine 入口。

- HITL-1 Design：Phase 1 设计方案评审（兼容旧卡片字段，按钮 value 新增 checkpoint=design）
- HITL-2 Deploy：Phase 4 Review 通过后是否部署（D3 新增）
"""
from __future__ import annotations

from typing import Any, Dict, Optional


CHECKPOINT_DESIGN = "design"
CHECKPOINT_DEPLOY = "deploy"


# ==========================================
# HITL-1: Design 方案评审
# ==========================================
def build_design_approval_card(
    demand_id: str,
    summary: str,
    design_doc: str = "",
    tech_doc_url: Optional[str] = None,
    tech_doc_title: Optional[str] = None,
) -> Dict[str, Any]:
    """Design 方案评审卡片。兼容 lark_client.build_approval_card 原展示。

    按钮 value 新增 `checkpoint=design` 字段，后续回调统一按此分发；
    `action` 字段保留（approve / reject）与旧回调兼容。
    """
    if tech_doc_url:
        link_text = tech_doc_title or "查看完整技术方案"
        detail_section = f"**📄 详细设计**\n[{link_text}]({tech_doc_url})"
    else:
        display_doc = design_doc[:500] + "..." if len(design_doc) > 500 else design_doc
        detail_section = f"**📄 详细设计 (部分)**\n{display_doc}"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🚀 AI 架构设计审批 (需求 ID: {demand_id})",
            },
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    "**AI 助手已完成技术方案设计，请审批：**\n\n"
                    f"**📝 方案摘要**\n{summary}\n\n"
                    f"{detail_section}"
                ),
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 同意并进入编码阶段"},
                        "type": "primary",
                        "value": {
                            "checkpoint": CHECKPOINT_DESIGN,
                            "action": "approve",
                            "demand_id": demand_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 驳回并要求修改"},
                        "type": "danger",
                        "value": {
                            "checkpoint": CHECKPOINT_DESIGN,
                            "action": "reject",
                            "demand_id": demand_id,
                        },
                    },
                ],
            },
        ],
    }


# ==========================================
# HITL-2: Deploy 部署审批
# ==========================================
def build_deploy_approval_card(
    demand_id: str,
    review_summary: str,
    artifact_url: Optional[str] = None,
    target_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Review 通过后的部署审批卡片。

    @params:
        demand_id: 需求 ID
        review_summary: Phase 4 Review 摘要（代码审查结论）
        artifact_url: 代码产物 / PR / 技术方案链接；可为空
        target_dir: 构建目标目录（调试信息，展示用）
    """
    info_lines = [
        "**Phase 4 代码审查已通过。即将构建镜像并运行，请确认是否部署：**",
        "",
        f"**📝 审查摘要**\n{review_summary or '（无摘要）'}",
    ]
    if artifact_url:
        info_lines.append(f"\n**📦 产物**\n[查看 artifact]({artifact_url})")
    if target_dir:
        info_lines.append(f"\n**🗂️ 目标目录** `{target_dir}`")

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🚢 AI 部署审批 (需求 ID: {demand_id})",
            },
            "template": "orange",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(info_lines)},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🚀 同意部署"},
                        "type": "primary",
                        "value": {
                            "checkpoint": CHECKPOINT_DEPLOY,
                            "action": "approve",
                            "demand_id": demand_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🛑 取消部署"},
                        "type": "danger",
                        "value": {
                            "checkpoint": CHECKPOINT_DEPLOY,
                            "action": "reject",
                            "demand_id": demand_id,
                        },
                    },
                ],
            },
        ],
    }
