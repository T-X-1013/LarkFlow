import concurrent.futures
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, Literal, Optional, Tuple

# 将项目根目录加入 sys.path，解决直接运行脚本时的模块导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入我们之前写的模块
from pipeline.lark_client import send_lark_card, send_lark_text
from pipeline.lark_doc_client import (
    LarkDocWriteError,
    create_tech_doc,
    grant_doc_access,
)
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
from pipeline.engine_control import (
    PipelineCancelled,
    check_lifecycle,
    get as get_pipeline_control,
    phase_to_stage,
)
from pipeline.contracts import CheckpointName, Stage, StageResult, StageStatus, TokenUsage
from pipeline.subsession import (
    finalize_subsession,
    init_subsession,
    load_subsession,
    merge_subsession_metrics,
    save_subsession,
    subsession_key,
)
from telemetry.hooks import (
    trace_approval_resume,
    trace_demand_start,
    trace_deploy_phase,
    trace_phase_execution,
    trace_phase_resume,
)

from dotenv import load_dotenv
load_dotenv()

# 会话持久化 (A1)：替代原先的进程内存 dict，支持进程重启恢复
STORE: SessionStore = default_store()


def _load_session(demand_id: str) -> Optional[Dict[str, Any]]:
    """从 STORE 读取 session 并重建 transient 字段 (client / logger)。

    D7：子 session 带 `role` / `parent_demand_id`，重建 logger 时把两者作为
    默认 extra 带入，使 reviewer 的每条日志都自动带 role 维度。
    """
    session = STORE.get(demand_id)
    if session is None:
        return None
    # transient 字段在持久化时被剥离，此处按需重建
    if "client" not in session and session.get("provider"):
        session["client"] = build_client(session["provider"])
    session["logger"] = get_logger(
        demand_id,
        session.get("phase"),
        role=session.get("role"),
        parent_demand_id=session.get("parent_demand_id"),
    )
    return session


def _save_session(demand_id: str, session: Dict[str, Any]) -> None:
    """
    把当前 session 写回持久化存储。

    @params:
        demand_id: 需求 ID
        session: 当前运行时 session

    @return:
        无返回值；直接把 session 保存到 STORE
    """
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


def _resolve_provider_for_new_demand(demand_id: str) -> str:
    """
    解析新 pipeline 首次启动时应使用的 provider。

    优先级：
    1. engine_control 中由 REST 预先写入的 ctl.provider
    2. 环境变量 `LLM_PROVIDER`
    """
    ctl = get_pipeline_control(demand_id)
    if ctl and ctl.provider:
        return get_provider_name(ctl.provider)
    return get_provider_name()


# ==========================================
# 2. 核心 Agent 循环 (处理 Tool Calling)
# ==========================================
# A3 可靠性参数：从环境变量读取，给出生产友好的默认值
def _env_int(name: str, default: int) -> int:
    """
    从环境变量读取正整数配置，并提供兜底默认值。

    @params:
        name: 环境变量名
        default: 读取失败或值非法时的默认值

    @return:
        返回不小于 1 的整数配置
    """
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

    last_exc: Optional[Exception] = None
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


def _prepare_tech_doc(
    demand_id: str,
    design_doc: str,
    logger,
    existing_token: Optional[str] = None,
    existing_url: Optional[str] = None,
    record_id: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    为审批卡准备飞书技术方案文档链接

    幂等：若 session.pending_approval 里已有 (token, url)，直接复用，避免重试重建文档。
    降级：建文档 / 授权任一失败都返回 (None, None)，调用方继续发截断卡，不阻塞审批链路。

    @params:
        demand_id: 需求 ID，用作文档标题
        design_doc: 技术方案全文 markdown
        logger: 阶段 logger，失败路径打 warning
        existing_token: pending_approval 里已缓存的 token；非空即复用
        existing_url: pending_approval 里已缓存的 url；非空即复用

    @return:
        (tech_doc_token, tech_doc_url)；失败时返回 (None, None)
    """
    if existing_url:
        return existing_token, existing_url

    title = f"技术方案 - {demand_id}"
    try:
        token, url = create_tech_doc(title, design_doc)
    except LarkDocWriteError as exc:
        logger.warning(
            f"tech doc create failed, fallback to truncated card: {exc}",
            extra={"event": "tech_doc_create_failed", "demand_id": demand_id},
        )
        return None, None

    # 按 env 配置授权审批目标：chat_id → openchat，open_id → openid
    approve_target = (os.getenv("LARK_DEMAND_APPROVE_TARGET") or "").strip()
    approve_type = (os.getenv("LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE") or "open_id").strip()
    member_type = "openchat" if approve_type == "chat_id" else "openid"
    if approve_target:
        try:
            grant_doc_access(token, approve_target, member_type=member_type, perm="full_access")
        except LarkDocWriteError as exc:
            logger.warning(
                f"tech doc grant failed, approver may get 403: {exc}",
                extra={"event": "tech_doc_grant_failed", "demand_id": demand_id},
            )
    else:
        logger.warning(
            "LARK_DEMAND_APPROVE_TARGET not configured, skip tech doc grant",
            extra={"event": "tech_doc_grant_skipped", "demand_id": demand_id},
        )

    # 成功拿到 url 后回写 Base 技术方案文档列，失败仅告警不阻塞审批链路
    if record_id:
        try:
            from pipeline.lark_bitable_listener import update_demand_tech_doc_url

            if not update_demand_tech_doc_url(record_id, url):
                logger.warning(
                    "tech doc url writeback to Base returned False",
                    extra={"event": "tech_doc_writeback_failed", "demand_id": demand_id},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"tech doc url writeback exception: {exc}",
                extra={"event": "tech_doc_writeback_exception", "demand_id": demand_id},
            )

    return token, url


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
    # D7：子 session 的 pause/stop 信号要跟着父 pipeline 走；
    # 非子 session（parent_demand_id 为空）直接用自身 demand_id
    lifecycle_id = session.get("parent_demand_id") or demand_id
    # D7：子 session 带 hitl_disabled 标记，拦截 ask_human_approval 防止 role reviewer
    # 误触发第 1/2 HITL 卡片（主 session 不受影响）
    hitl_disabled = bool(session.get("hitl_disabled"))

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
        # 每个 agent turn 前检查 pause/stop；长耗时 LLM 调用期间允许中断
        check_lifecycle(lifecycle_id)
        logger.info(
            "agent thinking",
            extra={"event": "agent_thinking", "phase": phase},
        )

        turn = _create_turn_with_retry(session, system_prompt, logger, phase)

        # B6 的 usage 埋点：单轮指标 + 累计到 session['metrics']
        turn_usage = getattr(turn, "usage", {}) or {}
        tool_name_for_metric = turn.tool_calls[0].name if turn.tool_calls else None
        # D7：子 reviewer 的 log_turn_metrics 带 role 维度，供 Grafana 拆图
        log_turn_metrics(
            logger,
            phase,
            turn_usage,
            tool_name_for_metric,
            role=session.get("role"),
        )
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
                    # D7：子 reviewer 不得触发 HITL —— 返回工具错误结果让 agent 自行纠正，
                    # 不挂起、不发卡片、保持并行 loop 继续运行
                    if hitl_disabled:
                        logger.warning(
                            "ask_human_approval blocked in sub reviewer",
                            extra={
                                "event": "hitl_blocked_subreviewer",
                                "phase": phase,
                                "role": session.get("role"),
                            },
                        )
                        append_tool_result(
                            session,
                            tool_call,
                            "ERROR: ask_human_approval is disabled in sub-reviewer context. "
                            "Emit <review-verdict> directly and finish your turn.",
                        )
                        continue
                    logger.info(
                        "approval requested",
                        extra={"event": "approval_requested", "phase": phase},
                    )
                    summary = tool_args.get("summary", "")
                    design_doc = tool_args.get("design_doc", "")

                    # 幂等：如果之前已为本需求建过 tech doc，复用；否则尝试新建 + 授权
                    prev_pending = session.get("pending_approval") or {}
                    tech_doc_token, tech_doc_url = _prepare_tech_doc(
                        demand_id,
                        design_doc,
                        logger,
                        existing_token=prev_pending.get("tech_doc_token"),
                        existing_url=prev_pending.get("tech_doc_url"),
                        record_id=session.get("record_id"),
                    )

                    session["pending_approval"] = {
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_name,
                        "summary": summary,
                        "design_doc": design_doc,
                        "tech_doc_token": tech_doc_token,
                        "tech_doc_url": tech_doc_url,
                    }
                    _save_session(demand_id, session)

                    lark_target = os.getenv("LARK_CHAT_ID")
                    if lark_target:
                        send_lark_card(
                            target=lark_target,
                            demand_id=demand_id,
                            summary=summary,
                            design_doc=design_doc,
                            tech_doc_url=tech_doc_url,
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
                    phase=session.get("phase"),
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
PHASE_DEPLOY_PENDING = "deploy_pending"  # 第 2 HITL：Review 通过后等部署审批
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

# 正常完成时的下一个阶段；由 default DAG 构造（YAML 驱动）
# DAG 定义在 pipeline/dag/default.yaml，stage 名为契约名（test/review），
# 映射到 engine phase 名（testing/reviewing）。deploying 不在 DAG 内，
# 作为 review 之后的终点动作保留。
def _build_next_phase_from_dag() -> Dict[str, str]:
    """
    根据默认 DAG 生成 engine 使用的阶段推进映射。

    @params:
        无

    @return:
        返回 `{当前 phase: 下一 phase}` 的映射字典
    """
    from pipeline.dag import default_dag
    from pipeline.engine_control import stage_to_phase

    dag = default_dag()
    order = [stage_to_phase(s) for s in dag.topo_order()]
    nxt: Dict[str, str] = {}
    for i in range(1, len(order)):
        nxt[order[i - 1]] = order[i]
    # 最后一个 DAG 阶段（reviewing）→ deploying 为 engine 既有约定
    if order:
        nxt[order[-1]] = PHASE_DEPLOYING
    return nxt


_NEXT_PHASE: Dict[str, str] = _build_next_phase_from_dag()

# 终端 banner 用的阶段序号与中文名；仅用于人眼可读的提示，不影响结构化日志
_PHASE_BANNER: Dict[str, tuple] = {
    PHASE_DESIGN: (1, "Design 设计"),
    PHASE_CODING: (2, "Coding 编码"),
    PHASE_TESTING: (3, "Testing 测试"),
    PHASE_REVIEWING: (4, "Reviewing 代码审查"),
    PHASE_DEPLOYING: (5, "Deploying 部署"),
}


# ==========================================
# D4: Stage 产物契约落盘
# ==========================================
# session 约定字段（dict，运行时 setdefault 注入）：
#   session["stage_results"]: Dict[stage_value, StageResult.model_dump(mode="json")]
#   session["_stage_start"]:  Dict[phase, {"ts": float, "tokens_in": int, "tokens_out": int}]
# stage_value 走 contracts.Stage ("design"/"coding"/"test"/"review")；
# phase 走 engine 内部 ("design"/"coding"/"testing"/"reviewing")，两者经 phase_to_stage 转换。


def _resolve_artifact_path(phase: str, session: Dict[str, Any]) -> Optional[str]:
    """按 phase 约定解析 artifact 路径；拿不到就返回 None。"""
    demand_id = session.get("demand_id")
    target_dir = session.get("target_dir")

    if phase == PHASE_DESIGN:
        # Design 产物优先用已创建的飞书技术方案文档 URL
        pending = session.get("pending_approval") or {}
        tech_url = pending.get("tech_doc_url")
        if tech_url:
            return tech_url
        if demand_id:
            candidate = os.path.join("tmp", str(demand_id), "design.md")
            return candidate if os.path.exists(candidate) else None
        return None

    # Coding / Testing / Reviewing 三阶段产物都沉淀在 target_dir
    if phase in (PHASE_CODING, PHASE_TESTING, PHASE_REVIEWING) and target_dir:
        return target_dir

    return None


def _record_stage_start(session: Dict[str, Any], phase: str) -> None:
    """阶段入场记快照（ts + tokens 基线），用于出场时算 duration / tokens delta。"""
    metrics = session.get("metrics") or {}
    session.setdefault("_stage_start", {})[phase] = {
        "ts": time.time(),
        "tokens_in": int(metrics.get("tokens_input", 0) or 0),
        "tokens_out": int(metrics.get("tokens_output", 0) or 0),
    }


def _record_stage_result(
    demand_id: str,
    phase: str,
    status: StageStatus,
    errors: Optional[list] = None,
    artifact_path: Optional[str] = None,
) -> None:
    """
    出场结算 StageResult 并写入 session['stage_results']。

    - phase: engine 内部命名（design/coding/testing/reviewing）；非契约四阶段（如 deploying）直接跳过
    - status: StageStatus 枚举（success/failed/rejected/pending）
    - tokens/duration 从 session['metrics'] 减去 session['_stage_start'][phase] 基线得到
    - artifact_path 为 None 时走 _resolve_artifact_path 兜底
    """
    stage = phase_to_stage(phase)
    if stage is None:
        return

    session = _load_session(demand_id)
    if not session:
        return

    metrics = session.get("metrics") or {}
    start = (session.get("_stage_start") or {}).get(phase) or {}
    tokens_in_delta = max(
        0,
        int(metrics.get("tokens_input", 0) or 0) - int(start.get("tokens_in", 0) or 0),
    )
    tokens_out_delta = max(
        0,
        int(metrics.get("tokens_output", 0) or 0) - int(start.get("tokens_out", 0) or 0),
    )
    duration_ms = (
        int((time.time() - float(start["ts"])) * 1000) if start.get("ts") else 0
    )

    if artifact_path is None:
        artifact_path = _resolve_artifact_path(phase, session)

    result = StageResult(
        stage=stage,
        status=status,
        artifact_path=artifact_path,
        tokens=TokenUsage(input=tokens_in_delta, output=tokens_out_delta),
        duration_ms=duration_ms,
        errors=list(errors or []),
    )
    session.setdefault("stage_results", {})[stage.value] = result.model_dump(mode="json")
    _save_session(demand_id, session)


def _mark_failed(demand_id: str, phase: str, error: str) -> None:
    """把 session 置为 failed 并落盘，同时飞书告警（如有配置）。

    D4：在翻转 session.phase 之前先把对应 stage 的 StageResult 记为 failed，
    errors 携带异常文本；phase 不在契约四阶段内（如 deploying）时自动短路。
    """
    # 先写 StageResult(failed)，再翻 session.phase；顺序反过来会导致下面
    # _load_session 里拿到的是 PHASE_FAILED 的 session，但 stage_results 仍应按真实 phase 记
    _record_stage_result(demand_id, phase, StageStatus.FAILED, errors=[error])

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


def _advance_to_phase(demand_id: str, phase: str) -> Optional[Dict[str, Any]]:
    """切换 session 到指定 phase，按需追加 kickoff 文本，并落盘。"""
    if phase not in _PHASE_CONFIG:
        raise ValueError(f"unknown phase: {phase}")
    logger = get_logger(demand_id, phase)
    banner = _PHASE_BANNER.get(phase)
    if banner:
        print(
            f"\n========== [需求 {demand_id}] Phase {banner[0]}: {banner[1]} 开始 ==========\n",
            flush=True,
        )
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


# ==========================================
# D5: Review verdict 解析 —— Phase 4 输出契约见 agents/phase4_review.md
# ==========================================
_VERDICT_RE = re.compile(
    r"<review-verdict>\s*(PASS|REGRESS)\s*</review-verdict>",
    re.IGNORECASE,
)
_FINDINGS_RE = re.compile(
    r"<review-findings>\s*(.*?)\s*</review-findings>",
    re.IGNORECASE | re.DOTALL,
)


def _extract_last_assistant_text(session: Dict[str, Any]) -> str:
    """反向找 session.messages 里最后一条 assistant 文本，支持 str / list[dict|str] 两种格式。"""
    for msg in reversed(session.get("messages") or []):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                return content
            continue
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text") or "")
                elif isinstance(b, str):
                    parts.append(b)
            text = "\n".join(p for p in parts if p)
            if text.strip():
                return text
    return ""


def _parse_review_verdict(
    session: Dict[str, Any],
) -> Tuple[Literal["pass", "regress"], str]:
    """解析 Phase 4 Agent 最后一条消息里的 <review-verdict> 与 <review-findings>。

    Returns:
        (verdict, findings)
        verdict: "pass" | "regress"
        findings: REGRESS 时的 findings 文本（可能为空字符串）

    保守策略：找不到标签 → ("pass", "")，避免误伤正常流程。
    """
    text = _extract_last_assistant_text(session)
    if not text:
        return "pass", ""

    # 取最后一个 verdict 标签（Agent 若在 few-shot 里引用了标签，应以末尾为准）
    matches = list(_VERDICT_RE.finditer(text))
    if not matches:
        return "pass", ""
    verdict = matches[-1].group(1).upper()
    if verdict != "REGRESS":
        return "pass", ""

    findings_match = _FINDINGS_RE.search(text)
    findings = findings_match.group(1).strip() if findings_match else ""
    return "regress", findings


def _try_regress(demand_id: str, findings: str, logger) -> bool:
    """Review 结论为 REGRESS 时尝试回退到 on_failure.to 指定的阶段。

    - D6：按 ctl.template 加载对应 DAG（default/feature/bugfix/refactor 等模板的 on_failure 各异）
    - 累计 regression.attempts，达 max_attempts 返回 False（上游置 failed）
    - 否则：递增计数、history 追加、以 user 消息形式注入 findings 作为下轮 Coding 的 kickoff
    - 返回 True 表示已调度回归，上游应把 current 切换到 policy.to
    """
    from pipeline import engine_control
    from pipeline.dag.schema import default_dag, load_template

    ctl = engine_control.get(demand_id)
    # 缺 ctl 时走 default_dag()，与旧测试的 monkey-patch 兼容；
    # 有 ctl 但模板名未知时同样回退，避免 Review 阶段因配置错误硬失败。
    if ctl is None:
        dag = default_dag()
    else:
        try:
            dag = load_template(ctl.template)
        except ValueError:
            dag = default_dag()
    review_node = dag.nodes.get(Stage.REVIEW)
    if review_node is None:
        return False
    policy = review_node.on_failure
    if policy is None or policy.action != "regress" or policy.to is None:
        return False

    session = _load_session(demand_id)
    if session is None:
        return False

    reg = session.setdefault("regression", {"attempts": 0, "history": []})
    if reg.get("attempts", 0) >= policy.max_attempts:
        logger.warning(
            "regression exhausted",
            extra={
                "event": "regression_exhausted",
                "phase": PHASE_REVIEWING,
                "attempts": reg.get("attempts", 0),
                "max": policy.max_attempts,
            },
        )
        return False

    reg["attempts"] = reg.get("attempts", 0) + 1
    reg.setdefault("history", []).append({
        "at": datetime.now(timezone.utc).isoformat(),
        "from": PHASE_REVIEWING,
        "to": policy.to.value,
        "findings_len": len(findings),
    })

    findings_block = findings.strip() or "(Reviewer 未提供具体 findings，请根据上一轮 Review 的整体评价自查并修复。)"
    kickoff_msg = (
        f"【自动回归 第 {reg['attempts']} 次 / 上限 {policy.max_attempts}】\n"
        f"上一轮 Code Review 结论为 REGRESS，需要在现有代码上定向修复以下问题后重跑 Test + Review：\n\n"
        f"{findings_block}\n\n"
        f"请严格按 findings 修复，不要引入无关重构；修复后 Phase 3 会重新执行测试。"
    )
    append_user_text(session, kickoff_msg)
    _save_session(demand_id, session)

    logger.info(
        "regression triggered",
        extra={
            "event": "regression_triggered",
            "phase": PHASE_REVIEWING,
            "to": policy.to.value,
            "attempt": reg["attempts"],
            "max": policy.max_attempts,
        },
    )
    return True


# ==========================================
# D7：Phase 4 Review 多视角并行 + 仲裁
# ==========================================
def _resolve_review_node_for_demand(demand_id: str):
    """按需求的 pipeline 模板解析 review 节点；无 ctl / 未知模板时返回 None
    （调用方会退化为单 agent 路径）。"""
    from pipeline import engine_control
    from pipeline.dag.schema import default_dag, load_template

    ctl = engine_control.get(demand_id)
    try:
        if ctl is not None and getattr(ctl, "template", None):
            dag = load_template(ctl.template)
        else:
            dag = default_dag()
    except Exception:  # noqa: BLE001
        return None
    return dag.nodes.get(Stage.REVIEW)


def _extract_worker_final_text(session: Dict[str, Any]) -> str:
    """取 worker agent 的最终文本输出，优先用 messages 协议，缺失时回退到 history。"""
    text = _extract_last_assistant_text(session)
    if text.strip():
        return text
    for msg in reversed(session.get("history") or []):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return ""


def _write_role_artifact(demand_id: str, role: str, text: str) -> str:
    """落盘 role reviewer 的评语 markdown，返回绝对路径。"""
    base = os.path.join("tmp", str(demand_id), "review_multi")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"review_{role}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")
    return path


def _build_role_kickoff(role: str, target_dir: Optional[str]) -> str:
    """构造 role worker 的首条 user 消息。

    目前 kickoff 非常薄：告知 role 名、目标目录、输出契约；
    具体审查视角由 prompt 文件承载（phase4_review_<role>.md）。
    """
    target_hint = target_dir or "../demo-app"
    return (
        f"你是 `{role}` 视角的 Reviewer。请对 `{target_hint}` 下本阶段修改过的代码做审查。\n"
        f"必须在最终回复里使用以下标签输出结论（供仲裁 Agent 解析）：\n"
        f"  <review-verdict>PASS|REGRESS</review-verdict>\n"
        f"  <review-findings>\n"
        f"  - severity: critical|high|medium|low\n"
        f"  - [file:line] 问题描述\n"
        f"  </review-findings>\n"
        f"禁止调用 `ask_human_approval`（会被运行时拒绝）；禁止 write/replace 文件。"
    )


def _reviewer_worker(
    parent_demand_id: str,
    role: str,
    prompt_file: str,
) -> Dict[str, Any]:
    """单个 role reviewer 的线程 worker。

    独立 sub session / 独立 LLM client / 独立 logger。任何异常都转成
    `{status: "failed", error: ...}` 返回，不向 ThreadPoolExecutor 抛出
    （避免一路炸掉另外两路）。
    """
    start_ts = time.time()
    subkey = subsession_key(parent_demand_id, role)
    base_result: Dict[str, Any] = {
        "role": role,
        "status": "failed",
        "artifact_path": None,
        "tokens_input": 0,
        "tokens_output": 0,
        "duration_ms": 0,
        "error": None,
    }
    try:
        sub = load_subsession(STORE, parent_demand_id, role)
        if sub is None:
            base_result["error"] = "subsession not initialized"
            base_result["duration_ms"] = int((time.time() - start_ts) * 1000)
            return base_result

        # 为子 session 初始化 provider 会话（history 为空 → 首次写入）
        client = build_client(sub["provider"])
        fresh = initialize_session(sub["provider"], _build_role_kickoff(role, sub.get("target_dir")), client)
        # 把 initialize_session 产生的 history / provider_state 并入 sub，其他字段不动
        sub["history"] = fresh.get("history", [])
        sub["provider_state"] = fresh.get("provider_state", {})
        sub["session_mode"] = fresh.get("session_mode")
        save_subsession(STORE, parent_demand_id, role, sub)

        # 跑 agent loop；run_agent_loop 内部按 subkey 反序化 session，
        # 重建 client/logger，并依据 session.parent_demand_id 把 lifecycle 锚定到父 pipeline
        system_prompt = load_prompt(prompt_file)
        # D7：给每路 reviewer 开独立 phase.reviewing span，attr 带 role，便于 Tempo 分色
        with trace_phase_execution(parent_demand_id, PHASE_REVIEWING, prompt_file, role=role) as span:
            completed = run_agent_loop(subkey, system_prompt)
            span.set_attribute("phase.completed", completed)
            span.set_attribute("phase.mode", "multi.worker")

        sub_final = load_subsession(STORE, parent_demand_id, role) or sub
        final_text = _extract_worker_final_text(sub_final)
        artifact_path = _write_role_artifact(parent_demand_id, role, final_text)

        duration_ms = int((time.time() - start_ts) * 1000)
        sub_metrics = sub_final.get("metrics") or {}
        status = "done" if completed and final_text.strip() else "failed"

        # 把子 session 标记终态，避免 list_active 把它当成孤儿 pipeline
        finalize_subsession(STORE, parent_demand_id, role, sub_final)

        return {
            "role": role,
            "status": status,
            "artifact_path": artifact_path,
            "tokens_input": int(sub_metrics.get("tokens_input", 0) or 0),
            "tokens_output": int(sub_metrics.get("tokens_output", 0) or 0),
            "duration_ms": duration_ms,
            "error": None if status == "done" else "empty final text or loop not completed",
        }
    except PipelineCancelled:
        base_result["status"] = "cancelled"
        base_result["error"] = "pipeline cancelled"
        base_result["duration_ms"] = int((time.time() - start_ts) * 1000)
        return base_result
    except Exception as exc:  # noqa: BLE001
        base_result["status"] = "failed"
        base_result["error"] = f"{type(exc).__name__}: {exc}"
        base_result["duration_ms"] = int((time.time() - start_ts) * 1000)
        return base_result


def _build_aggregator_kickoff(
    parent_demand_id: str,
    worker_results: list,
) -> str:
    """给仲裁 Agent 的首条 user 消息：列三路评语路径 + 成败状态。"""
    lines = [
        f"三位 Reviewer 已完成对需求 {parent_demand_id} 的并行评审。",
        "请读取每份评语并合并出最终 verdict。",
        "",
        "硬性规则：",
        "  1. 任一 role 判定 REGRESS ⇒ 全局 REGRESS。",
        "  2. 任一 role status=failed/cancelled ⇒ 默认 REGRESS（视角缺失不得放行）。",
        "  3. PASS 需三路同时 PASS 且评语无阻塞项。",
        "",
        "子评语清单：",
    ]
    for r in worker_results:
        role = r.get("role", "?")
        status = r.get("status", "?")
        path = r.get("artifact_path") or "(none)"
        err = r.get("error")
        suffix = f"  error: {err}" if err else ""
        lines.append(f"  - [{role}] status={status}, artifact={path}{suffix}")
    lines.append("")
    lines.append("请调用 file_editor.read 逐份阅读，然后产出：")
    lines.append("  <review-verdict>PASS|REGRESS</review-verdict>")
    lines.append("  <review-findings>（合并后的发现列表，去重、按 severity 排序）</review-findings>")
    return "\n".join(lines)


def _run_phase_multi(demand_id: str, node) -> bool:
    """Phase 4 Review 的并行执行器：N 个 role reviewer 并发 → 仲裁 Agent 合并。

    流程：
      1. parent session 入场记 stage_start
      2. 按 node.prompt_files 初始化 N 个 sub session（全部持久化）
      3. ThreadPoolExecutor(max_workers=node.parallel_workers) 跑 _reviewer_worker
      4. as_completed 收集结果；任意 worker 异常仅记录，不传播
      5. 合并 tokens / duration 回 parent session（含 by_role 维度）
      6. lifecycle 二次检查；被 pause/stop 则不跑 aggregator，返回 False
      7. parent session 跑 aggregator agent（单 agent loop，kickoff = 三路产物摘要）
      8. 继续走原 `_parse_review_verdict` → PASS/REGRESS 通路（在上游 resume_from_phase 里）
    """
    phase = PHASE_REVIEWING
    logger = get_logger(demand_id, phase)
    banner = _PHASE_BANNER[phase]
    print(
        f"\n========== [需求 {demand_id}] Phase {banner[0]}: {banner[1]} (多视角并行) 开始 ==========\n",
        flush=True,
    )
    logger.info(
        "phase multi review start",
        extra={
            "event": "phase_multi_start",
            "phase": phase,
            "roles": list(node.prompt_files.keys()),
            "parallel_workers": node.parallel_workers,
        },
    )

    # 入场快照
    parent = _load_session(demand_id)
    if parent is None:
        logger.error("parent session missing at multi review start")
        return False
    _record_stage_start(parent, phase)
    parent["phase"] = phase
    _save_session(demand_id, parent)

    try:
        check_lifecycle(demand_id)

        # 初始化 N 个 sub session（不跑 LLM，只落 key）
        for role in node.prompt_files.keys():
            sub = init_subsession(parent, role)
            save_subsession(STORE, demand_id, role, sub)

        worker_results: list = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(node.parallel_workers)),
            thread_name_prefix="reviewer",
        ) as ex:
            futures = {
                ex.submit(_reviewer_worker, demand_id, role, prompt_file): role
                for role, prompt_file in node.prompt_files.items()
            }
            for fut in concurrent.futures.as_completed(futures):
                role = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:  # noqa: BLE001
                    # _reviewer_worker 内部已 catch，这里兜底
                    result = {
                        "role": role,
                        "status": "failed",
                        "error": f"worker crashed outside try: {type(exc).__name__}: {exc}",
                        "tokens_input": 0,
                        "tokens_output": 0,
                        "duration_ms": 0,
                        "artifact_path": None,
                    }
                worker_results.append(result)
                logger.info(
                    "reviewer finished",
                    extra={
                        "event": "reviewer_finished",
                        "phase": phase,
                        "role": result.get("role"),
                        "status": result.get("status"),
                        "tokens_input": result.get("tokens_input"),
                        "tokens_output": result.get("tokens_output"),
                        "duration_ms": result.get("duration_ms"),
                    },
                )

        # 合并 metrics
        parent = _load_session(demand_id) or parent
        for r in worker_results:
            role = r["role"]
            sub_final = load_subsession(STORE, demand_id, role) or {"metrics": {
                "tokens_input": r.get("tokens_input", 0),
                "tokens_output": r.get("tokens_output", 0),
            }}
            merge_subsession_metrics(
                parent,
                sub_final,
                role,
                duration_ms=int(r.get("duration_ms", 0) or 0),
            )
        # 额外记录 subroles 到 session（非契约，前端/仪表盘可选用）
        parent.setdefault("review_multi", {})["subroles"] = worker_results
        _save_session(demand_id, parent)

        # 二次 lifecycle 检查：若被 pause/stop，不跑 aggregator
        check_lifecycle(demand_id)

        # 跑仲裁 agent（主 session + 单 agent loop）
        aggregator_prompt_file = node.aggregator_prompt_file
        if not aggregator_prompt_file:
            raise RuntimeError("parallel review node missing aggregator_prompt_file")
        aggregator_system = load_prompt(aggregator_prompt_file)

        # 用 user message 形式把三路评语喂给仲裁 agent
        parent = _load_session(demand_id) or parent
        append_user_text(parent, _build_aggregator_kickoff(demand_id, worker_results))
        _save_session(demand_id, parent)

        with trace_phase_execution(demand_id, phase, aggregator_prompt_file) as span:
            completed = run_agent_loop(demand_id, aggregator_system)
            span.set_attribute("phase.completed", completed)
            span.set_attribute("phase.mode", "multi")
            if completed:
                _record_stage_result(demand_id, phase, StageStatus.SUCCESS)
            return completed

    except PipelineCancelled:
        logger.info(
            "multi review cancelled",
            extra={"event": "phase_cancelled", "phase": phase},
        )
        return False
    except Exception as exc:
        logger.error(
            f"multi review crashed: {exc}",
            extra={"event": "phase_failed", "phase": phase},
            exc_info=True,
        )
        _mark_failed(demand_id, phase, str(exc))
        return False


def _run_phase(demand_id: str, phase: str) -> bool:
    """加载指定 phase 的 prompt 并运行 agent loop；异常时置 failed 态。

    D4：入场写 _stage_start 快照；正常完成写 StageResult(success)。
    pending_approval 与 PipelineCancelled 不写快照，保留中断语义；
    崩溃路径由 _mark_failed 内部补记 StageResult(failed)。

    D7：进入 reviewing 阶段时，若 DAG 模板把 review 节点声明为并行
    (`prompt_files` + `aggregator_prompt_file`)，自动分发到 `_run_phase_multi`。
    其他阶段保持原有单 agent 行为。
    """
    # D7 dispatch: Phase 4 并行模式
    if phase == PHASE_REVIEWING:
        node = _resolve_review_node_for_demand(demand_id)
        if node is not None and node.is_parallel:
            return _run_phase_multi(demand_id, node)

    prompt_file = _PHASE_CONFIG[phase]["prompt"]
    logger = get_logger(demand_id, phase)

    # 入场快照：记 ts + tokens 基线，供出场结算 duration / tokens delta
    session = _load_session(demand_id)
    if session is not None:
        _record_stage_start(session, phase)
        _save_session(demand_id, session)

    try:
        # 协作式 pause/stop 检查（未注册 pipeline 的旧入口会直接返回）
        check_lifecycle(demand_id)
        with trace_phase_execution(demand_id, phase, prompt_file) as span:
            system_prompt = load_prompt(prompt_file)
            completed = run_agent_loop(demand_id, system_prompt)
            span.set_attribute("phase.completed", completed)
            if completed:
                _record_stage_result(demand_id, phase, StageStatus.SUCCESS)
            # completed=False 且无异常 → pending_approval 挂起；StageResult 由后续
            # resume_after_approval 按 approved/rejected 补写，此处刻意不记
            return completed
    except PipelineCancelled:
        logger.info(
            "phase cancelled",
            extra={"event": "phase_cancelled", "phase": phase},
        )
        return False
    except Exception as exc:
        logger.error(
            f"phase crashed: {exc}",
            extra={"event": "phase_failed", "phase": phase},
            exc_info=True,
        )
        _mark_failed(demand_id, phase, str(exc))
        return False


def start_new_demand(
    demand_id: str,
    requirement: str,
    record_id: Optional[str] = None,
):
    """
    入口：飞书多维表格录入新需求，触发 Pipeline

    @params:
        demand_id: 需求 ID（Base 自增编号）
        requirement: 需求文本 / markdown
        record_id: Base 行 record_id；留存到 session 供后续回写技术方案链接等字段
    """
    with trace_demand_start(demand_id, PHASE_DESIGN) as span:
        logger = get_logger(demand_id, PHASE_DESIGN)
        banner = _PHASE_BANNER[PHASE_DESIGN]
        print(
            f"\n========== [需求 {demand_id}] Phase {banner[0]}: {banner[1]} 开始 ==========\n",
            flush=True,
        )
        logger.info(
            "demand started",
            extra={"event": "demand_started", "phase": PHASE_DESIGN},
        )

        # 将 Kratos 骨架模板物化为本次需求的产物目录，Phase 2 Agent 会在骨架基础上追加业务代码
        workspace_root, target_dir = _resolve_workspace_and_target()
        _ensure_target_scaffold(workspace_root, target_dir)
        span.set_attribute("target_dir", target_dir)
        logger.info(
            "scaffold ready",
            extra={"event": "scaffold_ready", "phase": PHASE_DESIGN},
        )

        provider = _resolve_provider_for_new_demand(demand_id)
        ctl = get_pipeline_control(demand_id)
        if ctl is not None and ctl.provider != provider:
            ctl.provider = provider
            ctl.touch()
        client = build_client(provider)
        session = initialize_session(provider, f"新需求：{requirement}", client)
        session["demand_id"] = demand_id
        session["target_dir"] = target_dir
        session["workspace_root"] = workspace_root
        session["phase"] = PHASE_DESIGN
        if record_id:
            session["record_id"] = record_id
        _save_session(demand_id, session)

        # 进入 Phase 1: Design
        completed = _run_phase(demand_id, PHASE_DESIGN)
        span.set_attribute("phase.completed", completed)

        if not completed:
            # 审批挂起或失败；区分两种语义用 session.phase
            latest = _load_session(demand_id)
            if latest and latest.get("pending_approval"):
                latest["phase"] = PHASE_DESIGN_PENDING
                _save_session(demand_id, latest)
                # D6 bugfix：把 design checkpoint 预埋到 ctl，让前端 GET /pipelines/{id}
                # 能看到 pending 状态的 checkpoint 条目（之前只在 approve/reject 时才 setdefault，
                # 导致前端 waiting_approval 期间渲染不出 Reject/Approve 按钮）。
                _seed_pending_checkpoint(demand_id, CheckpointName.DESIGN)
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
    with trace_phase_resume(demand_id, phase):
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

            # D5：Review 结束后解析 verdict；REGRESS 且未超上限 → 回退到 Coding
            if current == PHASE_REVIEWING:
                session = _load_session(demand_id)
                if session is not None:
                    verdict, findings = _parse_review_verdict(session)
                    if verdict == "regress":
                        if _try_regress(demand_id, findings, logger):
                            current = PHASE_CODING
                            continue
                        # 上限耗尽：置 failed，让外部接管（HITL 或人工介入）
                        _mark_failed(
                            demand_id,
                            PHASE_REVIEWING,
                            "regression exhausted: review kept returning REGRESS after max attempts",
                        )
                        return

            current = _NEXT_PHASE[current]

        # 第 2 HITL：Review 通过后挂起等部署审批，真正部署由
        # engine_api.approve_checkpoint(DEPLOY) → trigger_deploy 触发。
        # D6：模板的 review 节点若未挂 deploy checkpoint（例如 refactor 模板），
        # 则跳过部署审批，直接把 session.phase 置为 done。
        if _template_has_deploy_checkpoint(demand_id):
            _request_deploy_approval(demand_id, logger)
        else:
            _mark_done_without_deploy(demand_id, logger)


def resume_after_approval(demand_id: str, approved: bool, feedback: str):
    """
    由 lark_interaction.py 的 Webhook 调用：吸收审批结果 -> 交给 resume_from_phase 链式推进。
    """
    with trace_approval_resume(demand_id, approved):
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
            # Design 在挂起瞬间刻意未写 StageResult（见 _run_phase），
            # 审批通过后补记 success；duration 含审批等待时间，是已知口径
            _record_stage_result(demand_id, PHASE_DESIGN, StageStatus.SUCCESS)
            resume_from_phase(demand_id, PHASE_CODING)
        else:
            # 驳回：先把当次 Design 记为 rejected，feedback 作为 errors；
            # 重跑 Design 若成功会再次覆盖为 success，符合"最新真相"语义
            logger.info(
                "approval rejected, retry design",
                extra={"event": "approval_rejected", "phase": PHASE_DESIGN},
            )
            _record_stage_result(
                demand_id,
                PHASE_DESIGN,
                StageStatus.REJECTED,
                errors=[feedback] if feedback else [],
            )
            session = _load_session(demand_id)
            if session:
                session["phase"] = PHASE_DESIGN
                _save_session(demand_id, session)
            _run_phase(demand_id, PHASE_DESIGN)

# ==========================================
# 第 2 HITL：部署审批（D3）
# ==========================================
def _seed_pending_checkpoint(demand_id: str, name: CheckpointName) -> None:
    """把 pending 态 checkpoint 提前写进 ctl.checkpoints，让前端 GET 能看到。

    engine_api.approve/reject_checkpoint 仍会用 setdefault 兜底；此处的预埋只是把
    "等待审批" 这件事对 HTTP 客户端可见，避免前端只能通过飞书卡片得知 HITL 状态。
    """
    from pipeline import engine_control
    from pipeline.contracts import Checkpoint, StageStatus

    ctl = engine_control.get(demand_id)
    if ctl is None:
        return
    existing = ctl.checkpoints.get(name)
    if existing and existing.status != StageStatus.PENDING:
        # 已被 approve/reject 过就别覆盖，保留终态
        return
    ctl.checkpoints[name] = Checkpoint(
        name=name,
        status=StageStatus.PENDING,
        requested_at=int(time.time()),
    )
    ctl.touch()


def _template_has_deploy_checkpoint(demand_id: str) -> bool:
    """按当前 pipeline 的 template 判断 Review 节点是否挂了 deploy checkpoint。

    refactor 模板不挂 deploy（重构产物由人自行决定是否部署），其他模板默认挂。
    拿不到 ctl 时回退到 True，保持向后兼容。
    """
    from pipeline import engine_control
    from pipeline.dag.schema import load_template

    ctl = engine_control.get(demand_id)
    if ctl is None:
        return True
    try:
        dag = load_template(ctl.template)
    except ValueError:
        return True
    review_node = dag.nodes.get(Stage.REVIEW)
    if review_node is None:
        return True
    return review_node.checkpoint == CheckpointName.DEPLOY


def _mark_done_without_deploy(demand_id: str, logger) -> None:
    """refactor 等无 deploy HITL 的模板：Review 结束后直接把 session.phase 置为 done。"""
    session = _load_session(demand_id)
    if session is None:
        return
    session["phase"] = "done"
    _save_session(demand_id, session)
    logger.info(
        "pipeline finished without deploy checkpoint",
        extra={"event": "pipeline_done_no_deploy", "phase": "done"},
    )


def _request_deploy_approval(demand_id: str, logger) -> None:
    """Review 通过后挂起，推送部署审批卡片，等 approve_checkpoint(DEPLOY) 解挂。

    不触发真正部署；仅把 session.phase 置为 deploy_pending 并落盘。
    """
    from pipeline.lark_cards import build_deploy_approval_card

    session = _load_session(demand_id)
    if session is None:
        return

    # 从 session 里凑一份审查摘要：优先取 Agent 最后一次 assistant 文本，退化为占位
    review_summary = ""
    for msg in reversed(session.get("messages", []) or []):
        if msg.get("role") == "assistant":
            blocks = msg.get("content") or []
            if isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "text":
                        review_summary = (b.get("text") or "").strip()
                        break
                    if isinstance(b, str):
                        review_summary = b.strip()
                        break
            elif isinstance(blocks, str):
                review_summary = blocks.strip()
            if review_summary:
                break
    if not review_summary:
        review_summary = "代码审查已通过，等待部署确认。"

    target_dir = session.get("target_dir")
    session["phase"] = PHASE_DEPLOY_PENDING
    session["pending_deploy_approval"] = {
        "review_summary": review_summary[:2000],
        "target_dir": target_dir,
    }
    _save_session(demand_id, session)
    # D6 bugfix：同 design，让前端能在 deploy_pending 期间看到 checkpoint 条目
    _seed_pending_checkpoint(demand_id, CheckpointName.DEPLOY)

    lark_target = os.getenv("LARK_CHAT_ID")
    if lark_target:
        from pipeline.lark_client import send_lark_card_raw
        card = build_deploy_approval_card(
            demand_id=demand_id,
            review_summary=review_summary[:800],
            target_dir=target_dir,
        )
        try:
            send_lark_card_raw(lark_target, card)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"deploy card send failed: {exc}",
                extra={"event": "deploy_card_send_failed"},
            )
    else:
        logger.warning(
            "lark target not configured, skip deploy card",
            extra={"event": "lark_skip"},
        )
    logger.info(
        "deploy approval requested",
        extra={"event": "deploy_approval_requested", "phase": PHASE_DEPLOY_PENDING},
    )


def trigger_deploy(demand_id: str) -> None:
    """engine_api.approve_checkpoint(DEPLOY) 调用：真正执行部署，保留原终态逻辑。"""
    logger = get_logger(demand_id, PHASE_DEPLOYING)
    logger.info(
        "deploy approved, start deploy",
        extra={"event": "deploy_approved", "phase": PHASE_DEPLOYING},
    )
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
        session["pending_deploy_approval"] = None
        _save_session(demand_id, session)
        logger.info("demand done", extra={"event": "demand_done", "phase": PHASE_DONE})
    else:
        _mark_failed(demand_id, PHASE_DEPLOYING, "deploy reported failure")


# ==========================================
# 4. 部署编排 (A5)
# 实际构建/运行/失败分类由 pipeline/deploy_strategy.py 的 DeployStrategy 承担
# ==========================================
def deploy_app(demand_id: str) -> bool:
    """
    读取 session 中的 target_dir 与 deploy_strategy，委托策略执行部署。
    返回 True 表示成功，False 表示已捕获的失败。
    """
    with trace_deploy_phase(demand_id, PHASE_DEPLOYING) as span:
        logger = get_logger(demand_id, PHASE_DEPLOYING)
        logger.info("deploy started", extra={"event": "deploy_started", "phase": PHASE_DEPLOYING})

        session = _load_session(demand_id) or {}
        _, target_dir = _resolve_workspace_and_target(session.get("target_dir"))
        strategy = get_strategy(session.get("deploy_strategy"))
        span.set_attribute("target_dir", target_dir)
        span.set_attribute("deploy_strategy", strategy.name)

        outcome = strategy.deploy(target_dir, logger)
        span.set_attribute("deploy.success", outcome.success)
        span.set_attribute("deploy.access_url", outcome.access_url)
        span.set_attribute("deploy.reason", outcome.reason)

        lark_target = os.getenv("LARK_CHAT_ID")
        if outcome.success:
            logger.info("deploy success", extra={"event": "deploy_success", "phase": PHASE_DEPLOYING})
            if lark_target:
                send_lark_text(
                    lark_target,
                    f"🎉 需求 {demand_id} 部署成功！\n测试环境已就绪，服务地址：{outcome.access_url}",
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
