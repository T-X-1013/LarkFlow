"""D4 离线冒烟：不起 FastAPI / WS，直接构造四阶段 StageResult，
走 build_state 得到 PipelineState，打印 JSON，肉眼对照 §八 契约。

用途：
- 刘哈哈 D4 自检：验证 stage_results 反射链路
- tao D4 对接：这份 JSON 的 stages 结构就是 observability 要消费的 schema

用法：
    source venv/bin/activate
    python tests/smoke/d4_smoke_stage_contract.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 允许直接 `python tests/smoke/xxx.py` 跑
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 隔离 session store，避免污染真实数据
os.environ["LARKFLOW_SESSION_DIR"] = tempfile.mkdtemp(prefix="d4-smoke-")

from pipeline import engine, engine_control  # noqa: E402
from pipeline.contracts import StageStatus  # noqa: E402
from pipeline.persistence import default_store  # noqa: E402

engine.STORE = default_store()

DEMAND = "DEMAND-D4SMOKE"


def seed_session(demand_id: str, requirement: str) -> None:
    engine.STORE.save(
        demand_id,
        {
            "demand_id": demand_id,
            "provider": "openai",
            "target_dir": f"/tmp/{demand_id}",
            "phase": "design",
            "metrics": {"tokens_input": 0, "tokens_output": 0},
        },
    )
    engine_control.register(requirement, demand_id=demand_id)


def simulate_stage(
    demand_id: str,
    phase: str,
    tokens_in: int,
    tokens_out: int,
    duration_s: float,
    status: StageStatus,
    errors: list | None = None,
) -> None:
    """模拟一个阶段入场→出场的完整过程。"""
    session = engine._load_session(demand_id)
    engine._record_stage_start(session, phase)
    session["phase"] = phase
    engine._save_session(demand_id, session)

    # 模拟阶段期间累计 token
    session = engine._load_session(demand_id)
    session["metrics"]["tokens_input"] += tokens_in
    session["metrics"]["tokens_output"] += tokens_out
    engine._save_session(demand_id, session)

    time.sleep(duration_s)

    engine._record_stage_result(demand_id, phase, status, errors=errors)


def dump_state(demand_id: str, title: str) -> None:
    ctl = engine_control.get(demand_id)
    session = engine._load_session(demand_id)
    state = engine_control.build_state(ctl, session)
    print(f"\n--- {title} ---")
    print(state.model_dump_json(indent=2))


def main() -> None:
    print("=" * 70)
    print("D4 离线冒烟：StageResult 契约落盘 + build_state 反射")
    print("=" * 70)

    # 场景 1：四阶段全成功
    seed_session(DEMAND, "智能客服系统需求")
    simulate_stage(DEMAND, "design",    1200, 800,  0.05, StageStatus.SUCCESS)
    simulate_stage(DEMAND, "coding",    5000, 3500, 0.08, StageStatus.SUCCESS)
    simulate_stage(DEMAND, "testing",   1500, 900,  0.03, StageStatus.SUCCESS)
    simulate_stage(DEMAND, "reviewing", 2000, 1200, 0.04, StageStatus.SUCCESS)
    s = engine._load_session(DEMAND)
    s["phase"] = "done"
    engine._save_session(DEMAND, s)
    dump_state(DEMAND, f"GET /pipelines/{DEMAND}（四阶段全成功）")

    # 场景 2：Design 被驳回 → 重跑成功 → Testing 崩
    print("\n" + "=" * 70)
    print("失败链路冒烟：Design 驳回→重跑成功→Testing 崩")
    print("=" * 70)
    FAIL = "DEMAND-D4FAIL"
    seed_session(FAIL, "失败场景演示")

    simulate_stage(FAIL, "design", 500, 300, 0.02, StageStatus.REJECTED,
                   errors=["需求描述不清晰，缺少性能指标"])
    # 重跑 Design 成功（覆盖 rejected 为 success，契约层"最新真相"语义）
    simulate_stage(FAIL, "design", 800, 500, 0.02, StageStatus.SUCCESS)
    simulate_stage(FAIL, "coding", 3000, 2000, 0.03, StageStatus.SUCCESS)
    simulate_stage(FAIL, "testing", 200, 0, 0.01, StageStatus.FAILED,
                   errors=["pytest collection error: ImportError in test_order.py"])
    s = engine._load_session(FAIL)
    s["phase"] = "failed"
    engine._save_session(FAIL, s)
    dump_state(FAIL, f"GET /pipelines/{FAIL}（Testing 崩）")

    # 给 tao 的 observability 参考
    print("\n" + "=" * 70)
    print("给 tao 的采数路径参考（observability 消费点）")
    print("=" * 70)
    sample = engine._load_session(DEMAND)
    print("\nsession['stage_results'] 原始结构：")
    print(json.dumps(sample["stage_results"], indent=2, ensure_ascii=False))
    print("\n字段路径：")
    print("  session['stage_results'][<stage>].stage          → 'design'|'coding'|'test'|'review'")
    print("  session['stage_results'][<stage>].status         → 'success'|'failed'|'rejected'|'pending'")
    print("  session['stage_results'][<stage>].tokens.input   → int")
    print("  session['stage_results'][<stage>].tokens.output  → int")
    print("  session['stage_results'][<stage>].duration_ms    → int")
    print("  session['stage_results'][<stage>].artifact_path  → str | None")
    print("  session['stage_results'][<stage>].errors         → list[str]")
    print("\nDone.")


if __name__ == "__main__":
    main()
