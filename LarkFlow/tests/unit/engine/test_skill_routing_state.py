"""engine_control._parse_skill_routing 与 PipelineState.skill_routing 的契约测试。

确保 session["skill_routing"] 正确反序化为契约字段；异常数据不阻塞查询。
"""
from __future__ import annotations

import math
import unittest

from pipeline.core.engine_control import _parse_skill_routing


class ParseSkillRoutingTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(_parse_skill_routing(None))

    def test_non_dict_returns_none(self):
        self.assertIsNone(_parse_skill_routing("not a dict"))
        self.assertIsNone(_parse_skill_routing([]))

    def test_empty_dict_returns_none(self):
        self.assertIsNone(_parse_skill_routing({}))

    def test_full_payload_roundtrip(self):
        snapshot = _parse_skill_routing({
            "skills": ["skills/framework/kratos.md", "skills/transport/http.md"],
            "reasons": [
                {
                    "skill": "skills/framework/kratos.md",
                    "tier": "baseline",
                    "detail": "硬约束",
                    "score": 1.0,
                    "source": "",
                },
                {
                    "skill": "skills/transport/http.md",
                    "tier": "conditional",
                    "detail": "触发关键词「接口」",
                    "score": 1.0,
                    "source": "",
                },
            ],
        })
        self.assertIsNotNone(snapshot)
        self.assertEqual(len(snapshot.skills), 2)
        self.assertEqual(len(snapshot.reasons), 2)
        self.assertEqual(snapshot.reasons[0].tier, "baseline")
        self.assertEqual(snapshot.reasons[1].tier, "conditional")

    def test_corrupt_reason_entries_skipped(self):
        snapshot = _parse_skill_routing({
            "skills": ["skills/infra/redis.md"],
            "reasons": [
                "not-a-dict",
                {"skill": "skills/infra/redis.md", "tier": "route", "score": 1.0},
            ],
        })
        self.assertEqual(len(snapshot.reasons), 1)
        self.assertEqual(snapshot.reasons[0].skill, "skills/infra/redis.md")

    def test_source_field_preserved_for_semantic_channel(self):
        snapshot = _parse_skill_routing({
            "skills": ["skills/infra/redis.md"],
            "reasons": [{
                "skill": "skills/infra/redis.md",
                "tier": "route",
                "detail": "语义相似度 0.82",
                "score": 1.0,
                "source": "semantic",
            }],
        })
        self.assertEqual(snapshot.reasons[0].source, "semantic")

    def test_missing_reasons_but_skills_present_still_returns_snapshot(self):
        # 老 demand 可能没落 reasons；skills 非空也应返回
        snapshot = _parse_skill_routing({"skills": ["skills/framework/kratos.md"]})
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.skills, ["skills/framework/kratos.md"])
        self.assertEqual(snapshot.reasons, [])


if __name__ == "__main__":
    unittest.main()
