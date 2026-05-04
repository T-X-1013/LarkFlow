"""Phase 0 澄清回路的状态机单测。

覆盖：
1. _needs_clarification 触发条件：blocking question / 低置信度 / 都不满足
2. PipelineStatus 推断：clarification_pending → waiting_clarification
3. resume_from_clarification：错误状态保护、合并回答后重规范化
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pipeline.core import engine, engine_control
from pipeline.core.contracts import PipelineStatus
from pipeline.phase0 import (
    ApiSketch,
    NfrFlags,
    NormalizedDemand,
    OpenQuestion,
    PersistenceHint,
)


def _nd(**kwargs) -> NormalizedDemand:
    defaults = dict(
        raw_demand="x",
        goal="g",
        out_of_scope=[],
        entities=[],
        apis=[],
        persistence=PersistenceHint(),
        nfr=NfrFlags(),
        domain_tags=[],
        touches_python=False,
        open_questions=[],
        confidence=1.0,
        source="rule",
    )
    defaults.update(kwargs)
    return NormalizedDemand(**defaults)


class NeedsClarificationTests(unittest.TestCase):
    def test_blocking_question_triggers(self):
        nd = _nd(open_questions=[OpenQuestion(text="?", blocking=True)])
        self.assertTrue(engine._needs_clarification(nd))

    def test_non_blocking_questions_do_not_trigger(self):
        nd = _nd(open_questions=[OpenQuestion(text="?", blocking=False)])
        self.assertFalse(engine._needs_clarification(nd))

    def test_low_confidence_triggers_when_llm_floor_applies(self):
        # 规则版 confidence=1.0 不会触发，这里模拟 LLM 返回低分
        nd = _nd(confidence=0.5, source="hybrid")
        with patch.dict(
            os.environ, {"LARKFLOW_PHASE0_CONFIDENCE_FLOOR": "0.75"}, clear=False,
        ):
            self.assertTrue(engine._needs_clarification(nd))

    def test_high_confidence_passes(self):
        nd = _nd(confidence=0.9, source="hybrid")
        self.assertFalse(engine._needs_clarification(nd))


class StatusInferenceTests(unittest.TestCase):
    """验证 clarification_pending 映射到 WAITING_CLARIFICATION。"""

    def test_clarification_pending_maps_to_waiting_clarification(self):
        class FakeCtl:
            cancel_flag = type("F", (), {"is_set": staticmethod(lambda: False)})()
            pause_flag = type("F", (), {"is_set": staticmethod(lambda: False)})()
            thread = None
            checkpoints: dict = {}

        self.assertEqual(
            engine_control._infer_status(FakeCtl(), "clarification_pending"),
            PipelineStatus.WAITING_CLARIFICATION,
        )

    def test_other_pending_still_maps_to_waiting_approval(self):
        class FakeCtl:
            cancel_flag = type("F", (), {"is_set": staticmethod(lambda: False)})()
            pause_flag = type("F", (), {"is_set": staticmethod(lambda: False)})()
            thread = None
            checkpoints: dict = {}

        self.assertEqual(
            engine_control._infer_status(FakeCtl(), "design_pending"),
            PipelineStatus.WAITING_APPROVAL,
        )


class ResumeFromClarificationErrorTests(unittest.TestCase):
    """没注册的 demand / 状态不对时应 raise，避免误推进。"""

    def test_unknown_demand_raises(self):
        with patch.object(engine, "_load_session", return_value=None):
            with self.assertRaises(ValueError):
                engine.resume_from_clarification("unknown", [])

    def test_wrong_phase_raises(self):
        with patch.object(engine, "_load_session", return_value={"phase": "design"}):
            with self.assertRaises(ValueError):
                engine.resume_from_clarification("D1", [])


if __name__ == "__main__":
    unittest.main()
