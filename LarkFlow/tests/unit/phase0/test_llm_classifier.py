"""pipeline/phase0/llm_classifier.py 单测。

覆盖：
1. env 开关解析
2. 手动注入 call_fn：正常 JSON / 含 fence / 缺 goal → fallback / 异常降级
3. 置信度 floor 读取
4. hybrid 合并：LLM 缺字段用 rule 兜底
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from pipeline.phase0 import llm_classifier
from pipeline.phase0.normalizer import _normalize_rule


RAW = "让用户可以改昵称，最多 30 字，PATCH /users/{id}/nickname，需要幂等"


def _ok_payload() -> dict:
    return {
        "goal": "允许用户修改昵称",
        "out_of_scope": ["昵称历史"],
        "entities": ["User"],
        "apis": [{"method": "patch", "path": "/users/{id}/nickname", "purpose": "更新昵称"}],
        "persistence": {
            "needs_storage": True,
            "needs_migration": False,
            "tables": ["users"],
            "notes": "",
        },
        "nfr": {
            "auth": False,
            "idempotent": True,
            "rate_limit": False,
            "transactional": False,
            "high_concurrency": False,
        },
        "domain_tags": ["user"],
        "touches_python": False,
        "open_questions": [],
        "confidence": 0.9,
    }


class EnvSwitchTests(unittest.TestCase):
    def test_default_disabled(self):
        with patch.dict(os.environ, {"LARKFLOW_PHASE0_LLM_ENABLED": ""}, clear=False):
            self.assertFalse(llm_classifier.is_enabled())

    def test_enabled_on_whitelist(self):
        for v in ["1", "true", "yes", "on"]:
            with patch.dict(os.environ, {"LARKFLOW_PHASE0_LLM_ENABLED": v}, clear=False):
                self.assertTrue(llm_classifier.is_enabled(), v)

    def test_confidence_floor_default(self):
        with patch.dict(os.environ, {"LARKFLOW_PHASE0_CONFIDENCE_FLOOR": ""}, clear=False):
            self.assertEqual(llm_classifier.confidence_floor(), 0.75)

    def test_confidence_floor_override(self):
        with patch.dict(os.environ, {"LARKFLOW_PHASE0_CONFIDENCE_FLOOR": "0.5"}, clear=False):
            self.assertAlmostEqual(llm_classifier.confidence_floor(), 0.5)

    def test_confidence_floor_invalid_falls_back(self):
        with patch.dict(os.environ, {"LARKFLOW_PHASE0_CONFIDENCE_FLOOR": "abc"}, clear=False):
            self.assertEqual(llm_classifier.confidence_floor(), 0.75)


class ClassifyTests(unittest.TestCase):
    def _rule(self):
        return _normalize_rule(RAW)

    def test_injected_ok_payload_produces_hybrid(self):
        def _call(system, user, model):
            return json.dumps(_ok_payload())

        result = llm_classifier.classify(RAW, rule_fallback=self._rule(), call_fn=_call)
        self.assertEqual(result.source, "hybrid")
        self.assertAlmostEqual(result.confidence, 0.9)
        self.assertIn("user", result.domain_tags)
        self.assertTrue(result.nfr.idempotent)
        # hybrid 应保留 LLM 明确给出的 apis
        self.assertEqual(result.apis[0].method, "PATCH")

    def test_fenced_json_is_tolerated(self):
        def _call(system, user, model):
            return "```json\n" + json.dumps(_ok_payload()) + "\n```"

        result = llm_classifier.classify(RAW, rule_fallback=self._rule(), call_fn=_call)
        self.assertEqual(result.source, "hybrid")

    def test_missing_goal_falls_back_to_rule(self):
        bad = _ok_payload()
        bad["goal"] = ""

        def _call(system, user, model):
            return json.dumps(bad)

        result = llm_classifier.classify(RAW, rule_fallback=self._rule(), call_fn=_call)
        self.assertEqual(result.source, "rule")

    def test_invalid_json_falls_back(self):
        def _call(system, user, model):
            return "not json at all"

        result = llm_classifier.classify(RAW, rule_fallback=self._rule(), call_fn=_call)
        self.assertEqual(result.source, "rule")

    def test_exception_falls_back(self):
        def _call(system, user, model):
            raise RuntimeError("network")

        result = llm_classifier.classify(RAW, rule_fallback=self._rule(), call_fn=_call)
        self.assertEqual(result.source, "rule")

    def test_hybrid_fills_missing_fields_from_rule(self):
        """LLM 漏 persistence/nfr 时用规则版补齐。"""
        partial = _ok_payload()
        partial["persistence"] = {
            "needs_storage": False,
            "needs_migration": False,
            "tables": [],
            "notes": "",
        }
        partial["nfr"] = {
            "auth": False,
            "idempotent": False,  # LLM 漏了幂等信号
            "rate_limit": False,
            "transactional": False,
            "high_concurrency": False,
        }

        def _call(system, user, model):
            return json.dumps(partial)

        rule = self._rule()
        self.assertTrue(rule.nfr.idempotent, "规则版应识别出幂等")
        result = llm_classifier.classify(RAW, rule_fallback=rule, call_fn=_call)
        self.assertTrue(
            result.nfr.idempotent,
            "LLM 漏了 idempotent，hybrid 应用规则版补齐",
        )

    def test_empty_raw_returns_fallback(self):
        def _call(system, user, model):
            self.fail("不应调用 LLM")

        result = llm_classifier.classify(
            "", rule_fallback=_normalize_rule(""), call_fn=_call,
        )
        self.assertEqual(result.source, "rule")

    def test_no_call_fn_and_no_env_returns_fallback(self):
        """未注入 call_fn 且无 API key → 直接返回规则版。"""
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        env.pop("LARKFLOW_PHASE0_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = llm_classifier.classify(RAW, rule_fallback=self._rule())
        self.assertEqual(result.source, "rule")


if __name__ == "__main__":
    unittest.main()
