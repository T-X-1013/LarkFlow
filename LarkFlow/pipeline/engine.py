import os
import sys
import json
import subprocess
from typing import List, Dict, Any
import anthropic

# 将项目根目录加入 sys.path，解决直接运行脚本时的模块导入问题
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入我们之前写的模块
from pipeline.tools_schema import get_claude_tools
from pipeline.lark_interaction import send_lark_card, send_lark_text

from dotenv import load_dotenv
load_dotenv()

# --- 方式一：标准官方直连 (需配置 ANTHROPIC_API_KEY) ---
# client = anthropic.Anthropic()

# --- 方式二：公司内部转发代理 (需配置 ANTHROPIC_AUTH_TOKEN 和 ANTHROPIC_BASE_URL) ---
api_key = os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY")
base_url = os.getenv("ANTHROPIC_BASE_URL")

client = anthropic.Anthropic(
    api_key=api_key,
    base_url=base_url
)

# 模拟数据库/Redis 存储对话上下文
SESSION_STORE: Dict[str, List[Dict[str, Any]]] = {}

# ==========================================
# 1. 辅助函数：加载 Prompt 和 执行本地工具
# ==========================================
def load_prompt(phase_filename: str) -> str:
    """从 agents 目录加载 System Prompt"""
    path = os.path.join(os.path.dirname(__file__), "..", "agents", phase_filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def execute_local_tool(tool_name: str, tool_args: dict) -> str:
    """
    在本地或 Docker 容器中实际执行 Claude 调用的工具
    """
    print(f"  [Tool Execution] 正在执行 {tool_name}，参数: {tool_args}")
    
    if tool_name == "mock_db":
        query = tool_args.get("query", "")
        # 这里可以接入真实的 MySQL/TiDB 查询逻辑
        return f"Mock DB Result for '{query}': Table `users` has columns (id, name, created_at)."
        
    elif tool_name == "file_editor":
        action = tool_args.get("action")
        path = os.path.join(os.path.dirname(__file__), "..", tool_args.get("path", ""))
        
        try:
            if action == "read":
                with open(path, "r") as f: return f.read()
            elif action == "write":
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f: f.write(tool_args.get("content", ""))
                return f"Successfully wrote to {path}"
            elif action == "list_dir":
                return "\n".join(os.listdir(path))
            else:
                return f"Unsupported file_editor action: {action}"
        except Exception as e:
            return f"File operation failed: {str(e)}"
            
    elif tool_name == "run_bash":
        cmd = tool_args.get("command", "")
        # 在沙盒/Docker中执行命令
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        
    return f"Unknown tool: {tool_name}"


# ==========================================
# 2. 核心 Agent 循环 (处理 Tool Calling)
# ==========================================
def run_agent_loop(demand_id: str, system_prompt: str) -> bool:
    """
    运行 Claude 循环，直到它给出最终文本回复，或者调用了挂起工具(ask_human_approval)
    返回 True 表示当前阶段已完成，返回 False 表示被挂起。
    """
    messages = SESSION_STORE.get(demand_id, [])
    
    while True:
        print(f"\n[Agent] 正在思考 (Demand: {demand_id})...")
        
        # 支持通过环境变量自定义模型名称，以适配公司内部网关
        model_name = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        
        response = client.messages.create(
            model=model_name,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=get_claude_tools()
        )
        
        # 将 Claude 的回复加入历史
        messages.append({"role": "assistant", "content": response.content})
        SESSION_STORE[demand_id] = messages
        
        # 检查停止原因
        if response.stop_reason == "tool_use":
            tool_results = []
            suspend_pipeline = False
            
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_args = block.input
                    tool_use_id = block.id
                    
                    # 特殊处理：如果调用了 ask_human_approval，则发送飞书卡片并挂起
                    if tool_name == "ask_human_approval":
                        print(f"  [Pipeline] 触发审批节点，发送飞书卡片并挂起...")
                        webhook_url = os.getenv("LARK_WEBHOOK_URL")
                        if webhook_url:
                            send_lark_card(webhook_url, demand_id, tool_args["summary"], tool_args["design_doc"])
                        else:
                            print("  [Warning] 未配置 LARK_WEBHOOK_URL，跳过发送飞书卡片")
                        suspend_pipeline = True
                        break # 跳出工具处理循环
                    
                    # 常规工具执行
                    result_text = execute_local_tool(tool_name, tool_args)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result_text
                    })
            
            if suspend_pipeline:
                # 挂起当前循环，等待 Webhook 唤醒
                return False
                
            # 将工具执行结果发回给 Claude，继续下一轮循环
            messages.append({"role": "user", "content": tool_results})
            
        elif response.stop_reason == "end_turn":
            # Claude 完成了当前阶段的任务，给出了最终文本回复
            print(f"[Agent] 阶段任务完成: {response.content[0].text}")
            return True


# ==========================================
# 3. 状态机：阶段流转控制
# ==========================================
def start_new_demand(demand_id: str, requirement: str):
    """
    入口：飞书多维表格录入新需求，触发 Pipeline
    """
    print(f"========== 启动需求 {demand_id} ==========")
    SESSION_STORE[demand_id] = [{"role": "user", "content": f"新需求：{requirement}"}]
    
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
    messages = SESSION_STORE.get(demand_id)
    if not messages:
        return
        
    # 找到最后一个 assistant 消息中的 ask_human_approval tool_use_id
    last_msg = messages[-1]
    tool_use_id = next(b["id"] for b in last_msg["content"] if b["type"] == "tool_use" and b["name"] == "ask_human_approval")
    
    # 注入人类审批结果
    messages.append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": feedback
        }]
    })
    
    if approved:
        # 进入 Phase 2: Coding
        print(">> 进入 Phase 2: Coding")
        system_prompt = load_prompt("phase2_coding.md")
        completed = run_agent_loop(demand_id, system_prompt)
        
        if completed:
            # 自动进入 Phase 3: Test
            print(">> 进入 Phase 3: Test")
            messages.append({"role": "user", "content": "编码已完成，请开始编写测试用例并运行测试。"})
            system_prompt = load_prompt("phase3_test.md")
            test_completed = run_agent_loop(demand_id, system_prompt)
            
            if test_completed:
                # 自动进入 Phase 4: Review
                print(">> 进入 Phase 4: Review")
                messages.append({"role": "user", "content": "测试已通过，请作为 Code Reviewer 进行最终的代码审查，并修复任何不符合规范的代码。"})
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
            f.write("FROM golang:1.21-alpine\nWORKDIR /app\nCOPY . .\nRUN go mod tidy && go build -o main .\nCMD [\"/app/main\"]\nEXPOSE 8080")
            
    try:
        # 2. 构建镜像
        print("   正在构建镜像 demo-app:latest...")
        subprocess.run(["docker", "build", "-t", "demo-app", "."], cwd=app_dir, check=True)
        
        # 3. 停止旧容器（如果存在）
        subprocess.run(["docker", "rm", "-f", "demo-app-container"], stderr=subprocess.DEVNULL)
        
        # 4. 运行新容器
        print("   正在启动容器 demo-app-container (端口 8080)...")
        subprocess.run(["docker", "run", "-d", "--name", "demo-app-container", "-p", "8080:8080", "demo-app"], check=True)
        
        print(">> 部署成功！")
        webhook_url = os.getenv("LARK_WEBHOOK_URL")
        if webhook_url:
            send_lark_text(webhook_url, f"🎉 需求 {demand_id} 部署成功！\n测试环境已就绪，体验地址：http://localhost:8080")
            
    except subprocess.CalledProcessError as e:
        print(f">> 部署失败: {e}")
        webhook_url = os.getenv("LARK_WEBHOOK_URL")
        if webhook_url:
            send_lark_text(webhook_url, f"❌ 需求 {demand_id} 部署失败，请检查构建日志。")

# ==========================================
# 测试入口 (模拟运行)
# ==========================================
if __name__ == "__main__":
    # 模拟飞书收到新需求
    start_new_demand("DEMAND-001", "在 users 表中增加一个 age 字段，并提供一个 HTTP 接口来更新用户的 age。")
    
    # 模拟用户在飞书点击了“同意”
    # resume_after_approval("DEMAND-001", True, "设计合理，同意进入开发阶段。")
    
