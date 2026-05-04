"""pipeline/skills/gate.py 单测。

覆盖：
1. check_coverage：baseline/conditional 为 mandatory，route 为 optional；
   mandatory 全读才 passed=True。
2. 空输入与异常条目的容错。
3. 开关与重试上限 env 解析。
4. render_remediation_message 包含缺失的 mandatory skill 名字。
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pipeline.skills.gate import (
    SkillGateVerdict,
    check_coverage,
    is_enabled,
    max_retries,
)


def _routing(reasons):
    return {"skills": [r["skill"] for r in reasons], "reasons": reasons}


BASELINE = {"skill": "skills/framework/kratos.md", "tier": "baseline"}
BASELINE_2 = {"skill": "skills/lang/error.md", "tier": "baseline"}
CONDITIONAL = {"skill": "skills/transport/http.md", "tier": "conditional"}
ROUTE = {"skill": "skills/infra/redis.md", "tier": "route"}


class CheckCoverageTests(unittest.TestCase):
    def test_all_read_passes(self):
        verdict = check_coverage(
            _routing([BASELINE, CONDITIONAL, ROUTE]),
            [
                "skills/framework/kratos.md",
                "skills/transport/http.md",
                "skills/infra/redis.md",
            ],
        )
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.missing_mandatory, [])
        self.assertEqual(verdict.missing_optional, [])

    def test_missing_baseline_fails(self):
        verdict = check_coverage(
            _routing([BASELINE, CONDITIONAL]),
            ["skills/transport/http.md"],
        )
        self.assertFalse(verdict.passed)
        self.assertEqual(verdict.missing_mandatory, ["skills/framework/kratos.md"])
        self.assertEqual(verdict.missing_optional, [])

    def test_missing_conditional_fails(self):
        verdict = check_coverage(
            _routing([BASELINE, CONDITIONAL]),
            ["skills/framework/kratos.md"],
        )
        self.assertFalse(verdict.passed)
        self.assertEqual(verdict.missing_mandatory, ["skills/transport/http.md"])

    def test_missing_route_is_optional(self):
        verdict = check_coverage(
            _routing([BASELINE, ROUTE]),
            ["skills/framework/kratos.md"],
        )
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.missing_optional, ["skills/infra/redis.md"])

    def test_null_routing_passes(self):
        self.assertTrue(check_coverage(None, []).passed)

    def test_empty_reasons_passes(self):
        self.assertTrue(check_coverage({"skills": [], "reasons": []}, None).passed)

    def test_corrupt_reason_entries_ignored(self):
        verdict = check_coverage(
            {
                "skills": ["x"],
                "reasons": [
                    "not-a-dict",
                    {"skill": "", "tier": "baseline"},  # 空 skill
                    BASELINE,
                ],
            },
            ["skills/framework/kratos.md"],
        )
        self.assertTrue(verdict.passed)

    def test_duplicate_skill_deduped(self):
        verdict = check_coverage(
            _routing([BASELINE, BASELINE]),
            [],
        )
        self.assertEqual(verdict.missing_mandatory, ["skills/framework/kratos.md"])

    def test_remediation_message_includes_missing_skills(self):
        verdict = check_coverage(
            _routing([BASELINE, CONDITIONAL, ROUTE]),
            [],
        )
        message = verdict.render_remediation_message()
        self.assertIn("skills/framework/kratos.md", message)
        self.assertIn("skills/transport/http.md", message)
        self.assertIn("skills/infra/redis.md", message)  # optional 以"建议"形式出现

    def test_remediation_empty_when_passed(self):
        verdict = SkillGateVerdict(passed=True)
        self.assertEqual(verdict.render_remediation_message(), "")

    def test_to_dict_shape(self):
        verdict = check_coverage(
            _routing([BASELINE]),
            ["skills/framework/kratos.md"],
            attempt=3,
        )
        d = verdict.to_dict()
        self.assertEqual(d["passed"], True)
        self.assertEqual(d["attempt"], 3)
        self.assertIn("skills/framework/kratos.md", d["read"])


class EnvSwitchTests(unittest.TestCase):
    def test_enabled_by_default(self):
        # 未设置环境变量即视为默认启用
        env = dict(os.environ)
        env.pop("LARKFLOW_SKILL_GATE_ENABLED", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(is_enabled())

    def test_explicit_off_values(self):
        for val in ["0", "false", "no", "off"]:
            with patch.dict(os.environ, {"LARKFLOW_SKILL_GATE_ENABLED": val}, clear=False):
                self.assertFalse(is_enabled(), f"{val} 应视为关闭")

    def test_max_retries_default(self):
        with patch.dict(os.environ, {"LARKFLOW_SKILL_GATE_MAX_RETRIES": ""}, clear=False):
            self.assertEqual(max_retries(), 2)

    def test_max_retries_valid(self):
        with patch.dict(os.environ, {"LARKFLOW_SKILL_GATE_MAX_RETRIES": "5"}, clear=False):
            self.assertEqual(max_retries(), 5)

    def test_max_retries_invalid_falls_back(self):
        with patch.dict(os.environ, {"LARKFLOW_SKILL_GATE_MAX_RETRIES": "abc"}, clear=False):
            self.assertEqual(max_retries(), 2)

    def test_max_retries_negative_clamped(self):
        with patch.dict(os.environ, {"LARKFLOW_SKILL_GATE_MAX_RETRIES": "-1"}, clear=False):
            self.assertEqual(max_retries(), 0)


if __name__ == "__main__":
    unittest.main()
