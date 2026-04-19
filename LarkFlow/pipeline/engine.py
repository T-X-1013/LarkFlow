import os
import sys
import subprocess
import time
from typing import Dict, Any

# 将项目根目录加入 sys.path，解决直接运行脚本时的模块导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入我们之前写的模块
from pipeline.lark_interaction import send_lark_card, send_lark_text
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

from dotenv import load_dotenv
load_dotenv()

# 模拟数据库/Redis 存储对话上下文
SESSION_STORE: Dict[str, Dict[str, Any]] = {}

# ==========================================
# 1. 辅助函数：加载 Prompt
# ==========================================
def load_prompt(phase_filename: str) -> str:
    """从 agents 目录加载 System Prompt"""
    path = os.path.join(os.path.dirname(__file__), "..", "agents", phase_filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _run_checked_command(command: list, cwd: str = None) -> subprocess.CompletedProcess:
    """执行命令并在失败时保留 stdout/stderr，便于分类部署错误。"""
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _collect_process_output(exc: subprocess.CalledProcessError) -> str:
    parts = []
    if exc.output:
        parts.append(exc.output.strip())
    if exc.stderr:
        parts.append(exc.stderr.strip())
    return "\n".join(part for part in parts if part).strip()


def _tail_text(text: str, max_lines: int = 20) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _classify_deploy_failure(stage: str, details: str) -> str:
    text = (details or "").lower()

    if (
        "failed to fetch anonymous token" in text
        or "auth.docker.io" in text
        or "registry.docker.io" in text
        or "deadlineexceeded" in text
        or "i/o timeout" in text
    ):
        return "Docker 外网访问失败，基础镜像或仓库元数据拉取超时。"

    if "apk add" in text and ("temporary error" in text or "fetch " in text):
        return "Alpine 软件源访问失败，构建依赖安装未完成。"

    if "go mod download" in text or "go mod tidy" in text:
        return "Go 依赖下载失败。"

    if "requires go >=" in text:
        return "Go 版本与项目要求不匹配。"

    if "go build" in text or "build failed" in text:
        return "Go 编译失败。"

    if "requires cgo to work" in text or "cgo_enabled=0" in text:
        return "SQLite 驱动依赖 CGO，但当前镜像未正确启用。"

    if stage == "docker run":
        return "容器启动命令执行失败。"

    if stage == "container health":
        return "容器已启动但应用很快退出。"

    return f"{stage} 失败。"


def _inspect_container_failure(container_name: str) -> str:
    """检查容器是否立即退出；若已退出则返回带分类的错误信息。"""
    time.sleep(2)

    inspect_result = _run_checked_command(
        ["docker", "inspect", "-f", "{{.State.Status}}", container_name]
    )
    status = inspect_result.stdout.strip()
    if status == "running":
        return ""

    logs_result = subprocess.run(
        ["docker", "logs", container_name],
        capture_output=True,
        text=True,
    )
    log_text = "\n".join(
        part.strip() for part in [logs_result.stdout, logs_result.stderr] if part and part.strip()
    )
    reason = _classify_deploy_failure("container health", log_text)
    detail = _tail_text(log_text)
    if detail:
        return f"{reason}\n最近日志:\n{detail}"
    return reason


# ==========================================
# 2. 核心 Agent 循环 (处理 Tool Calling)
# ==========================================
def run_agent_loop(demand_id: str, system_prompt: str) -> bool:
    """
    运行 Agent 循环，直到它给出最终文本回复，或者调用了挂起工具(ask_human_approval)
    返回 True 表示当前阶段已完成，返回 False 表示被挂起。
    """
    session = SESSION_STORE.get(demand_id)
    if not session:
        return False

    while True:
        print(f"\n[Agent] 正在思考 (Demand: {demand_id}, Provider: {session['provider']})...")

        turn = create_turn(session, system_prompt)

        if turn.tool_calls:
            for tool_call in turn.tool_calls:
                tool_name = tool_call.name
                tool_args = tool_call.arguments

                # 特殊处理：如果调用了 ask_human_approval，则发送飞书卡片并挂起
                if tool_name == "ask_human_approval":
                    print("  [Pipeline] 触发审批节点，发送飞书卡片并挂起...")
                    session["pending_approval"] = {
                        "tool_call_id": tool_call.id,
                        "tool_name": tool_name,
                        "summary": tool_args.get("summary", ""),
                        "design_doc": tool_args.get("design_doc", "")
                    }
                    
                    lark_target = os.getenv("LARK_CHAT_ID") or os.getenv("LARK_WEBHOOK_URL")
                    if lark_target:
                        send_lark_card(
                            lark_target,
                            demand_id,
                            session["pending_approval"]["summary"],
                            session["pending_approval"]["design_doc"]
                        )
                    else:
                        print("  [Warning] 未配置 LARK_CHAT_ID 或 LARK_WEBHOOK_URL，跳过发送飞书卡片")
                    return False

                # 常规工具执行
                workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                target_dir = session.get(
                    "target_dir",
                    os.path.abspath(os.path.join(workspace_root, "..", "demo-app")),
                )
                tool_ctx = ToolContext(
                    demand_id=demand_id,
                    workspace_root=workspace_root,
                    target_dir=target_dir,
                    logger=session.get("logger"),
                )
                result_text = execute_local_tool(tool_name, tool_args, tool_ctx)
                append_tool_result(session, tool_call, result_text)

        elif turn.finished:
            # Agent 完成了当前阶段的任务，给出了最终文本回复
            final_text = "\n".join(turn.text_blocks).strip()
            print(f"[Agent] 阶段任务完成: {final_text}")
            return True


# ==========================================
# 3. 状态机：阶段流转控制
# ==========================================
def start_new_demand(demand_id: str, requirement: str):
    """
    入口：飞书多维表格录入新需求，触发 Pipeline
    """
    print(f"========== 启动需求 {demand_id} ==========")
    provider = get_provider_name()
    client = build_client(provider)
    SESSION_STORE[demand_id] = initialize_session(provider, f"新需求：{requirement}", client)

    # 进入 Phase 1: Design
    system_prompt = load_prompt("phase1_design.md")
    completed = run_agent_loop(demand_id, system_prompt)

    if not completed:
        print(f"========== 需求 {demand_id} 已挂起，等待人类审批 ==========")

def resume_after_approval(demand_id: str, approved: bool, feedback: str):
    """
    由 lark_interaction.py 的 Webhook 调用
    """
    print(f"========== 唤醒需求 {demand_id} (审批: {approved}) ==========")
    session = SESSION_STORE.get(demand_id)
    if not session:
        return

    pending_approval = session.get("pending_approval")
    if not pending_approval:
        print(">> 当前会话没有待处理的审批节点")
        return

    append_tool_result(
        session,
        ToolCall(
            id=pending_approval["tool_call_id"],
            name=pending_approval["tool_name"],
            arguments={
                "summary": pending_approval["summary"],
                "design_doc": pending_approval["design_doc"]
            }
        ),
        feedback
    )
    session["pending_approval"] = None

    if approved:
        # 进入 Phase 2: Coding
        print(">> 进入 Phase 2: Coding")
        system_prompt = load_prompt("phase2_coding.md")
        completed = run_agent_loop(demand_id, system_prompt)

        if completed:
            # 自动进入 Phase 3: Test
            print(">> 进入 Phase 3: Test")
            append_user_text(session, "编码已完成，请开始编写测试用例并运行测试。")
            system_prompt = load_prompt("phase3_test.md")
            test_completed = run_agent_loop(demand_id, system_prompt)

            if test_completed:
                # 自动进入 Phase 4: Review
                print(">> 进入 Phase 4: Review")
                append_user_text(session, "测试已通过，请作为 Code Reviewer 进行最终的代码审查，并修复任何不符合规范的代码。")
                system_prompt = load_prompt("phase4_review.md")
                review_completed = run_agent_loop(demand_id, system_prompt)

                if review_completed:
                    print(f"========== 需求 {demand_id} 全部流程结束，准备部署 ==========")
                    deploy_app(demand_id)
    else:
        # 驳回，继续留在 Phase 1 重新设计
        print(">> 驳回，重新进入 Phase 1: Design")
        system_prompt = load_prompt("phase1_design.md")
        run_agent_loop(demand_id, system_prompt)

# ==========================================
# 4. Docker 部署逻辑
# ==========================================
def deploy_app(demand_id: str):
    """
    将 AI 写的代码打包成 Docker 镜像并运行
    """
    print(">> 开始 Docker 部署...")
    app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "demo-app"))

    # 1. 如果 AI 没有写 Dockerfile，我们帮它生成一个极简版的
    dockerfile_path = os.path.join(app_dir, "Dockerfile")
    if not os.path.exists(dockerfile_path):
        with open(dockerfile_path, "w") as f:
            f.write(
                "FROM golang:1.22-alpine AS builder\n\n"
                "RUN apk add --no-cache build-base\n\n"
                "WORKDIR /src\n\n"
                "COPY go.mod go.sum ./\n"
                "RUN go mod download\n\n"
                "COPY . .\n\n"
                "RUN CGO_ENABLED=1 GOOS=linux go build -o /out/main .\n\n"
                "FROM golang:1.22-alpine\n\n"
                "WORKDIR /app\n\n"
                "COPY --from=builder /out/main /app/main\n\n"
                "EXPOSE 8080\n\n"
                "CMD [\"/app/main\"]\n"
            )

    try:
        # 2. 构建镜像
        print("   正在构建镜像 demo-app:latest...")
        _run_checked_command(["docker", "build", "-t", "demo-app", "."], cwd=app_dir)

        # 3. 停止旧容器（如果存在）
        subprocess.run(["docker", "rm", "-f", "demo-app-container"], capture_output=True, text=True)

        # 4. 运行新容器
        print("   正在启动容器 demo-app-container (端口 8080)...")
        run_result = _run_checked_command(
            ["docker", "run", "-d", "--name", "demo-app-container", "-p", "8080:8080", "demo-app"]
        )

        container_id = run_result.stdout.strip()
        if container_id:
            print(f"   容器已创建: {container_id}")

        container_failure = _inspect_container_failure("demo-app-container")
        if container_failure:
            raise RuntimeError(container_failure)

        print(">> 部署成功！")
        lark_target = os.getenv("LARK_CHAT_ID") or os.getenv("LARK_WEBHOOK_URL")
        if lark_target:
            send_lark_text(lark_target, f"🎉 需求 {demand_id} 部署成功！\n测试环境已就绪，体验地址：http://localhost:8080")

    except subprocess.CalledProcessError as e:
        command_name = " ".join(e.cmd[:2]) if isinstance(e.cmd, (list, tuple)) and len(e.cmd) >= 2 else str(e.cmd)
        details = _collect_process_output(e)
        reason = _classify_deploy_failure(command_name, details)
        print(f">> 部署失败: {reason}")
        if details:
            print(_tail_text(details))
        lark_target = os.getenv("LARK_CHAT_ID") or os.getenv("LARK_WEBHOOK_URL")
        if lark_target:
            send_lark_text(lark_target, f"❌ 需求 {demand_id} 部署失败：{reason}")
    except RuntimeError as e:
        reason = str(e)
        print(f">> 部署失败: {reason}")
        lark_target = os.getenv("LARK_CHAT_ID") or os.getenv("LARK_WEBHOOK_URL")
        if lark_target:
            send_lark_text(lark_target, f"❌ 需求 {demand_id} 部署失败：{reason}")

# ==========================================
# 测试入口 (模拟运行)
# ==========================================
if __name__ == "__main__":
    # 模拟飞书收到新需求
    start_new_demand("DEMAND-001", "在 users 表中增加一个 age 字段，并提供一个 HTTP 接口来更新用户的 age。")

    # 模拟用户在飞书点击了"同意"
    # resume_after_approval("DEMAND-001", True, "设计合理，同意进入开发阶段。")
