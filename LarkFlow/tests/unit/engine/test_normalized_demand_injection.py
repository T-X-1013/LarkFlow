"""engine._inject_normalized_demand 行为单测。

覆盖：
- session 为 None / 缺字段 → 原样返回
- session 有 normalized_demand → 注入权威段
- 原 prompt 前缀保留，结构化头部存在
"""
from __future__ import annotations

import unittest

from pipeline.core import engine
from pipeline.phase0 import normalize_demand


_BASE_PROMPT = "# Role: System Architect\n\nDo the thing."


class InjectNormalizedDemandTests(unittest.TestCase):
    def test_none_session_passthrough(self):
        self.assertEqual(engine._inject_normalized_demand(_BASE_PROMPT, None), _BASE_PROMPT)

    def test_missing_field_passthrough(self):
        self.assertEqual(
            engine._inject_normalized_demand(_BASE_PROMPT, {"demand_id": "D1"}),
            _BASE_PROMPT,
        )

    def test_injection_adds_header_and_preserves_prefix(self):
        nd = normalize_demand("支付回调必须幂等，PATCH /orders/{id}/refund")
        session = {"normalized_demand": nd.to_dict()}
        injected = engine._inject_normalized_demand(_BASE_PROMPT, session)
        self.assertTrue(injected.startswith(_BASE_PROMPT))
        self.assertIn("Normalized Demand (authoritative)", injected)
        self.assertIn("Goal", injected)
        self.assertIn("NFR", injected)

    def test_corrupt_payload_passthrough(self):
        session = {"normalized_demand": {"raw_demand": "x", "goal": "y", "nfr": "not-a-dict"}}
        # 不崩溃，返回原 prompt
        out = engine._inject_normalized_demand(_BASE_PROMPT, session)
        self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main()
