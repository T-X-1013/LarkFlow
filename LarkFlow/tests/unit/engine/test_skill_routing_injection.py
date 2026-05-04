"""engine._inject_skill_routing 的行为单测。

覆盖：
1. session 为 None / 缺 skill_routing / skills 为空 → 原样返回 prompt。
2. 有 skill_routing → 在 prompt 尾部追加 `## Skill Routing (authoritative)` 段，
   且段内列出所有 skill。
3. 注入段在原 prompt 之后（不污染 prompt 头部的业务指令）。
"""
from __future__ import annotations

import unittest

from pipeline.core import engine
from pipeline.skills.router import route_from_text


_BASE_PROMPT = "# Role: System Architect\n\nDo the thing."


class InjectSkillRoutingTests(unittest.TestCase):
    def test_returns_prompt_unchanged_when_session_is_none(self):
        self.assertEqual(
            engine._inject_skill_routing(_BASE_PROMPT, None),
            _BASE_PROMPT,
        )

    def test_returns_prompt_unchanged_when_skill_routing_missing(self):
        self.assertEqual(
            engine._inject_skill_routing(_BASE_PROMPT, {"demand_id": "D1"}),
            _BASE_PROMPT,
        )

    def test_returns_prompt_unchanged_when_skills_empty(self):
        session = {"skill_routing": {"skills": [], "reasons": []}}
        self.assertEqual(
            engine._inject_skill_routing(_BASE_PROMPT, session),
            _BASE_PROMPT,
        )

    def test_appends_authoritative_block_with_all_skills(self):
        routing = route_from_text("提供一个 HTTP 接口更新用户资料")
        session = {"skill_routing": routing.to_dict()}
        injected = engine._inject_skill_routing(_BASE_PROMPT, session)
        self.assertTrue(injected.startswith(_BASE_PROMPT))
        self.assertIn("## Skill Routing (authoritative)", injected)
        for skill in routing.skills:
            self.assertIn(skill, injected)

    def test_injection_preserves_base_prompt_prefix(self):
        routing = route_from_text("新增订单表，支持分页查询")
        session = {"skill_routing": routing.to_dict()}
        injected = engine._inject_skill_routing(_BASE_PROMPT, session)
        # 原 prompt 内容必须完整保留在开头
        self.assertEqual(injected.split("## Skill Routing")[0].strip(), _BASE_PROMPT.strip())

    def test_tier_labels_present_when_reasons_provided(self):
        routing = route_from_text("支付回调必须幂等")
        session = {"skill_routing": routing.to_dict()}
        injected = engine._inject_skill_routing(_BASE_PROMPT, session)
        self.assertIn("[baseline]", injected)
        self.assertIn("[conditional]", injected)


if __name__ == "__main__":
    unittest.main()
