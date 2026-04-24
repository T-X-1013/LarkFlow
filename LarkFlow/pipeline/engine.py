import concurrent.futures
import os
import random
import shutil
import sys
import time
from typing import Dict, Any

# 将项目根目录加入 sys.path，解决直接运行脚本时的模块导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入我们之前写的模块
from pipeline.lark_client import send_lark_card, send_lark_text
from pipeline.llm_adapter import (
    ToolCall,
    append_tool_result,
    append_user_text,
    build_client,
    create_turn,
    get_provider_name,
    initialize_session,
)
from pipeline.tools_runtime import ToolContext, execute as execute_local_tool
from pipeline.persistence import SessionStore, default_store
from pipeline.observability import accumulate_metrics, get_logger, log_turn_metrics
from pipeline.deploy_strategy import get_strategy

from dotenv import load_dotenv
load_dotenv()

# 会话持久化 (A1)：替代原先的进程内存 dict，支持进程重启恢复
STORE: SessionStore = default_store()


def _load_session(demand_id: str) -> Dict[str, Any] | None:
    """从 STORE 读取 session 并重建 transient 字段 (client / logger)。"""
    session = STORE.get(demand_id)
    if session is None:
        return None
    # transient 字段在持久化时被剥离，此处按需重建
    if "client" not in session and session.get("provider"):
        session["client"] = build_client(session["provider"])
    session["logger"] = get_logger(demand_id, session.get("phase"))
    return session


def _save_session(demand_id: str, session: Dict[str, Any]) -> None:
    STORE.save(demand_id, session)

# ==========================================
# 1. 辅助函数：加载 Prompt
# ==========================================
def load_prompt(phase_filename: str) -> str:
    """从 agents 目录加载 System Prompt"""
    path = os.path.join(os.path.dirname(__file__), "..", "agents", phase_filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# 骨架物化标记：`go.mod` 存在即视为 target_dir 已是 Kratos 布局
_SCAFFOLD_MARKER = "go.mod"

# 骨架模板在 workspace_root 内的相对位置
_SCAFFOLD_TEMPLATE_RELPATH = os.path.join("templates", "kratos-skeleton")


def _ensure_target_scaffold(workspace_root: str, target_dir: str) -> None:
    """将 Kratos 骨架模板复制到 target_dir，作为每个新需求的只读起点

    @params:
        workspace_root: LarkFlow/ 目录的绝对路径，内部有 templates/kratos-skeleton/
        target_dir: 本次需求产物目录的绝对路径，一般是 <repo>/demo-app

    @return:
        无返回值；以下情况抛异常：
          - 模板目录不存在
          - target_dir 已有文件但缺失 `go.mod`（未知状态，拒绝覆盖）

    @notes:
        - 幂等：target_dir 下有 `go.mod` 时直接返回，不做任何覆盖，支持 pipeline 重启后
          的 resume 流程。
        - 空目录安全：target_dir 存在但为空时，删除后再 copytree，避免 shutil 报错。
    """
    template_dir = os.path.join(workspace_root, _SCAFFOLD_TEMPLATE_RELPATH)
    marker = os.path.join(target_dir, _SCAFFOLD_MARKER)

    if os.path.isfile(marker):
        return

    if not os.path.isdir(template_dir):
        raise FileNotFoundError(
            f"Kratos 骨架模板缺失：{template_dir}；请确认 LarkFlow/{_SCAFFOLD_TEMPLATE_RELPATH}/ 存在"
        )

    if os.path.exists(target_dir):
        if os.listdir(target_dir):
            raise RuntimeError(
                f"target_dir 非空且无 {_SCAFFOLD_MARKER}，状态不明确，拒绝覆盖：{target_dir}；"
                f"请先人工清理或检查上一次需求产物"
            )
        os.rmdir(target_dir)

    shutil.copytree(template_dir, target_dir)


def _resolve_workspace_and_target(session_target: str = None) -> tuple:
    """统一解析 workspace_root 与 target_dir，供 start / resume 与工具调用共用

    @params:
        session_target: 已存储在 session 中的 target_dir，优先使用

    @return:
        (workspace_root 绝对路径, target_dir 绝对路径)
    """
    workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target_dir = session_target or os.path.abspath(os.path.join(workspace_root, "..", "demo-app"))
    return workspace_root, target_dir


# ==========================================
# 2. 核心 Agent 循环 (处理 Tool Calling)
# ==========================================
# A3 可靠性参数：从环境变量读取，给出生产友好的默认值
def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _create_turn_with_retry(session, system_prompt, logger, phase):
    """
    封装 create_turn：单轮超时 + 指数退避重试。

    超时: 环境变量 AGENT_TURN_TIMEOUT (默认 120s)，单位秒。
    重试: AGENT_MAX_RETRIES (默认 3)，遇到超时或任何异常都退避后重试。
    退避: 2^attempt 秒 + jitter；与 llm_adapter.py 内部 RateLimit 重试解耦。
    """
    timeout = _env_int("AGENT_TURN_TIMEOUT", 120)
    max_retries = _env_int("AGENT_MAX_RETRIES", 3)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(create_turn, session, system_prompt)
                return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            last_exc = TimeoutError(f"create_turn exceeded {timeout}s")
            logger.warning(
                f"agent turn timeout (attempt {attempt + 1}/{max_retries})",
                extra={"event": "agent_turn_timeout", "phase": phase},
            )
        except Exception as exc:  # noqa: BLE001 — 重试覆盖所有 LLM/网络异常
            last_exc = exc
            logger.warning(
                f"agent turn error (attempt {attempt + 1}/{max_retries}): {exc}",
                extra={"event": "agent_turn_error", "phase": phase},
            )

        if attempt < max_retries - 1:
            backoff = 2 ** attempt + random.uniform(0, 0.5)
            time.sleep(backoff)

    assert last_exc is not None
    raise last_exc


def run_agent_loop(demand_id: str, system_prompt: str) -> bool:
    """
    运行 Agent 循环，直到它给出最终文本回复，或者调用了挂起工具(ask_human_approval)
    返回 True 表示当前阶段已完成，返回 False 表示被挂起 / 超轮数 / 连续空响应。

    A3 保护：单轮超时、最大轮数、连续空响应退出、LLM 失败指数退避重试。
    """
    session = _load_session(demand_id)
    if not session:
        return False
    logger = session["logger"]
    phase = session.get("phase")

    max_turns = _env_int("AGENT_MAX_TURNS", 30)
    max_empty_streak = _env_int("AGENT_MAX_EMPTY_STREAK", 3)
    turn_count = 0
    empty_streak = 0

    while True:
        if turn_count >= max_turns:
            raise RuntimeError(
                f"agent loop exceeded AGENT_MAX_TURNS={max_turns} at phase {phase}"
            )
        turn_count += 1
        logger.info(
            "agent thinking",
            extra={"event": "agent_thinking", "phase": phase},
        )

        turn = _create_turn_with_retry(session, system_prompt, logger, phase)

        # B6 的 usage 埋点：单轮指标 + 累计到 session['metrics']
        turn_usage = getattr(turn, "usage", {}) or {}
        tool_name_for_metric = turn.tool_calls[0].name if turn.tool_calls else None
        log_turn_metrics(logger, phase, turn_usage, tool_name_for_metric)
        accumulate_metrics(session, turn_usage)

        # 空响应检测：既没有工具调用、也没有 finished 标志、也没有文本内容
        if not turn.tool_calls and not turn.finished and not any(
            (block or "").strip() for block in (turn.text_blocks or [])
        ):
            empty_streak += 1
            logger.warning(
                f"empty turn streak {empty_streak}/{max_empty_streak}",
                extra={"event": "agent_empty_turn", "phase": phase},
            )
            if empty_streak >= max_empty_streak:
                raise RuntimeError(
                    f"agent returned {empty_streak} consecutive empty turns at phase {phase}"
                )
            continue
        empty_streak = 0

        if turn.tool_calls:
            for tool_call in turn.tool_calls:
                tool_name = tool_call.name
                tool_args = tool_call.arguments

                # 特殊处理：如果调用了 ask_human_approval，则发送飞书卡片并挂起
                if tool_name == "ask_human_approval":
                    logger.info(
                        "approval requested",
                        extra={"event": "approval_requested", "phase": phase},
                    )
                    session["pending_approval"] = {
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_name,
                        "summary": tool_args.get("summary", ""),
                        "design_doc": tool_args.get("design_doc", "")
                    }
                    _save_session(demand_id, session)

                    lark_target = os.getenv("LARK_CHAT_ID")
                    if lark_target:
                        send_lark_card(
                            lark_target,
                            demand_id,
                            session["pending_approval"]["summary"],
                            session["pending_approval"]["design_doc"]
                        )
                    else:
                        logger.warning(
                            "lark target not configured, skip card",
                            extra={"event": "lark_skip"},
                        )
                    return False

                # 常规工具执行：workspace_root 与 target_dir 在 start_new_demand 阶段已固化到 session
                workspace_root, target_dir = _resolve_workspace_and_target(session.get("target_dir"))
                tool_ctx = ToolContext(
                    demand_id=demand_id,
                    workspace_root=workspace_root,
                    target_dir=target_dir,
                    logger=session.get("logger"),
                )
                result_text = execute_local_tool(tool_name, tool_args, tool_ctx)
                append_tool_result(session, tool_call, result_text)

            # 每轮工具执行完成后持久化，支持中途崩溃恢复
            _save_session(demand_id, session)

        elif turn.finished:
            # Agent 完成了当前阶段的任务
            logger.info(
                "phase finished",
                extra={"event": "phase_finished", "phase": phase},
            )
            _save_session(demand_id, session)
            return True


# ==========================================
# 3. 状态机：阶段流转控制 (A2)
# ==========================================
# 合法阶段常量；session["phase"] 仅能取这些值
PHASE_DESIGN = "design"
PHASE_DESIGN_PENDING = "design_pending"  # 审批挂起态
PHASE_CODING = "coding"
PHASE_TESTING = "testing"
PHASE_REVIEWING = "reviewing"
PHASE_DEPLOYING = "deploying"
PHASE_DONE = "done"
PHASE_FAILED = "failed"

# 每个阶段对应的 system prompt 文件与进入时追加到 history 的 user kickoff 文本
# design 的 kickoff 由 start_new_demand 注入；coding 的 kickoff 由 resume_after_approval 注入(审批 feedback)
_PHASE_CONFIG: Dict[str, Dict[str, Any]] = {
    PHASE_DESIGN: {"prompt": "phase1_design.md", "kickoff": None},
    PHASE_CODING: {"prompt": "phase2_coding.md", "kickoff": None},
    PHASE_TESTING: {
        "prompt": "phase3_test.md",
        "kickoff": "编码已完成，请开始编写测试用例并运行测试。",
    },
    PHASE_REVIEWING: {
        "prompt": "phase4_review.md",
        "kickoff": "测试已通过，请作为 Code Reviewer 进行最终的代码审查，并修复任何不符合规范的代码。",
    },
    # deploying 不走 agent loop，仅登记为合法阶段，prompt 为 None
    PHASE_DEPLOYING: {"prompt": None, "kickoff": None},
}

# 正常完成时的下一个阶段；用于链式推进
_NEXT_PHASE: Dict[str, str] = {
    PHASE_CODING: PHASE_TESTING,
    PHASE_TESTING: PHASE_REVIEWING,
    PHASE_REVIEWING: PHASE_DEPLOYING,
}


def _mark_failed(demand_id: str, phase: str, error: str) -> None:
    """把 session 置为 failed 并落盘，同时飞书告警（如有配置）。"""
    session = _load_session(demand_id)
    if not session:
        return
    session["phase"] = PHASE_FAILED
    session["last_error"] = {"phase": phase, "message": error}
    _save_session(demand_id, session)

    # A3 验收要求：失败态落地后发飞书告警，方便值班人员介入
    lark_target = os.getenv("LARK_CHAT_ID")
    if lark_target:
        try:
            send_lark_text(
                lark_target,
                f"⚠️ 需求 {demand_id} 在 {phase} 阶段失败：{error}",
            )
        except Exception:  # noqa: BLE001 — 告警失败不能影响主流程
            pass


def _advance_to_phase(demand_id: str, phase: str) -> Dict[str, Any] | None:
    """切换 session 到指定 phase，按需追加 kickoff 文本，并落盘。"""
    if phase not in _PHASE_CONFIG:
        raise ValueError(f"unknown phase: {phase}")
    logger = get_logger(demand_id, phase)
    logger.info("enter phase", extra={"event": "phase_enter", "phase": phase})
    session = _load_session(demand_id)
    if not session:
        return None
    session["phase"] = phase
    kickoff = _PHASE_CONFIG[phase]["kickoff"]
    if kickoff:
        append_user_text(session, kickoff)
    _save_session(demand_id, session)
    return session


def _run_phase(demand_id: str, phase: str) -> bool:
    """加载指定 phase 的 prompt 并运行 agent loop；异常时置 failed 态。"""
    prompt_file = _PHASE_CONFIG[phase]["prompt"]
    logger = get_logger(demand_id, phase)
    try:
        system_prompt = load_prompt(prompt_file)
        return run_agent_loop(demand_id, system_prompt)
    except Exception as exc:
        logger.error(
            f"phase crashed: {exc}",
            extra={"event": "phase_failed", "phase": phase},
            exc_info=True,
        )
        _mark_failed(demand_id, phase, str(exc))
        return False


def start_new_demand(demand_id: str, requirement: str):
    """
    入口：飞书多维表格录入新需求，触发 Pipeline
    """
    logger = get_logger(demand_id, PHASE_DESIGN)
    logger.info(
        "demand started",
        extra={"event": "demand_started", "phase": PHASE_DESIGN},
    )

    # 将 Kratos 骨架模板物化为本次需求的产物目录，Phase 2 Agent 会在骨架基础上追加业务代码
    workspace_root, target_dir = _resolve_workspace_and_target()
    _ensure_target_scaffold(workspace_root, target_dir)
    logger.info(
        "scaffold ready",
        extra={"event": "scaffold_ready", "phase": PHASE_DESIGN},
    )

    provider = get_provider_name()
    client = build_client(provider)
    session = initialize_session(provider, f"新需求：{requirement}", client)
    session["target_dir"] = target_dir
    session["workspace_root"] = workspace_root
    session["phase"] = PHASE_DESIGN
    _save_session(demand_id, session)

    # 进入 Phase 1: Design
    completed = _run_phase(demand_id, PHASE_DESIGN)

    if not completed:
        # 审批挂起或失败；区分两种语义用 session.phase
        latest = _load_session(demand_id)
        if latest and latest.get("pending_approval"):
            latest["phase"] = PHASE_DESIGN_PENDING
            _save_session(demand_id, latest)
            logger.info(
                "demand suspended awaiting approval",
                extra={"event": "demand_suspended", "phase": PHASE_DESIGN_PENDING},
            )


def resume_from_phase(demand_id: str, phase: str) -> None:
    """从指定 phase 起链式推进，直到挂起 / 完成 / 失败。

    支持中途失败后的断点续跑。合法入口 phase: coding / testing / reviewing / deploying。
    """
    allowed = {PHASE_CODING, PHASE_TESTING, PHASE_REVIEWING, PHASE_DEPLOYING}
    if phase not in allowed:
        raise ValueError(
            f"resume_from_phase: unsupported phase {phase!r}, must be one of {sorted(allowed)}"
        )
    logger = get_logger(demand_id, phase)
    logger.info("resume from phase", extra={"event": "phase_resume", "phase": phase})

    # coding → testing → reviewing 依靠 agent loop，每一阶段完成后进入下一阶段
    current = phase
    while current in (PHASE_CODING, PHASE_TESTING, PHASE_REVIEWING):
        if _advance_to_phase(demand_id, current) is None:
            return
        completed = _run_phase(demand_id, current)
        if not completed:
            # agent 挂起、超轮数或异常。_run_phase 已按需打日志/置 failed
            return
        current = _NEXT_PHASE[current]

    # current == PHASE_DEPLOYING：执行部署并以结果定 phase 终态
    if _advance_to_phase(demand_id, PHASE_DEPLOYING) is None:
        return
    try:
        deploy_ok = deploy_app(demand_id)
    except Exception as exc:
        logger.error(
            f"deploy crashed: {exc}",
            extra={"event": "phase_failed", "phase": PHASE_DEPLOYING},
            exc_info=True,
        )
        _mark_failed(demand_id, PHASE_DEPLOYING, str(exc))
        return

    session = _load_session(demand_id)
    if session is None:
        return
    if deploy_ok:
        session["phase"] = PHASE_DONE
        _save_session(demand_id, session)
        logger.info("demand done", extra={"event": "demand_done", "phase": PHASE_DONE})
    else:
        _mark_failed(demand_id, PHASE_DEPLOYING, "deploy reported failure")


def resume_after_approval(demand_id: str, approved: bool, feedback: str):
    """
    由 lark_interaction.py 的 Webhook 调用：吸收审批结果 -> 交给 resume_from_phase 链式推进。
    """
    logger = get_logger(demand_id)
    logger.info(
        "approval resumed",
        extra={"event": "approval_resumed", "approved": approved},
    )
    session = _load_session(demand_id)
    if not session:
        return

    pending_approval = session.get("pending_approval")
    if not pending_approval:
        logger.warning(
            "no pending approval to resume",
            extra={"event": "approval_missing"},
        )
        return

    append_tool_result(
        session,
        ToolCall(
            id=pending_approval["tool_call_id"],
            name=pending_approval["tool_name"],
            arguments={
                "summary": pending_approval["summary"],
                "design_doc": pending_approval["design_doc"],
            },
        ),
        feedback,
    )
    session["pending_approval"] = None
    _save_session(demand_id, session)

    if approved:
        resume_from_phase(demand_id, PHASE_CODING)
    else:
        # 驳回：回到 Phase 1 重新设计
        logger.info(
            "approval rejected, retry design",
            extra={"event": "approval_rejected", "phase": PHASE_DESIGN},
        )
        session = _load_session(demand_id)
        if session:
            session["phase"] = PHASE_DESIGN
            _save_session(demand_id, session)
        _run_phase(demand_id, PHASE_DESIGN)

# ==========================================
# 4. 部署编排 (A5)
# 实际构建/运行/失败分类由 pipeline/deploy_strategy.py 的 DeployStrategy 承担
# ==========================================
def deploy_app(demand_id: str) -> bool:
    """
    读取 session 中的 target_dir 与 deploy_strategy，委托策略执行部署。
    返回 True 表示成功，False 表示已捕获的失败。
    """
    logger = get_logger(demand_id, PHASE_DEPLOYING)
    logger.info("deploy started", extra={"event": "deploy_started", "phase": PHASE_DEPLOYING})

    session = _load_session(demand_id) or {}
    _, target_dir = _resolve_workspace_and_target(session.get("target_dir"))
    strategy = get_strategy(session.get("deploy_strategy"))

    outcome = strategy.deploy(target_dir, logger)

    lark_target = os.getenv("LARK_CHAT_ID")
    if outcome.success:
        logger.info("deploy success", extra={"event": "deploy_success", "phase": PHASE_DEPLOYING})
        if lark_target:
            send_lark_text(
                lark_target,
                f"🎉 需求 {demand_id} 部署成功！\n测试环境已就绪，体验地址：{outcome.access_url}",
            )
        return True

    logger.error(
        f"deploy failed: {outcome.reason}",
        extra={"event": "deploy_failed", "phase": PHASE_DEPLOYING},
    )
    if lark_target:
        send_lark_text(lark_target, f"❌ 需求 {demand_id} 部署失败：{outcome.reason}")
    return False

# ==========================================
# 测试入口 (模拟运行)
# ==========================================
if __name__ == "__main__":
    # 模拟飞书收到新需求
    start_new_demand("DEMAND-001", "在 users 表中增加一个 age 字段，并提供一个 HTTP 接口来更新用户的 age。")

    # 模拟用户在飞书点击了"同意"
    # resume_after_approval("DEMAND-001", True, "设计合理，同意进入开发阶段。")
