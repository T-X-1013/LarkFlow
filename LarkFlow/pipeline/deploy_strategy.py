"""部署策略 (A5)

把 deploy_app 中硬编码的 Dockerfile + Go/Docker 逻辑抽成可替换的策略。
engine.py 仅负责编排（飞书通知、session 状态更新），具体构建/运行/失败分类
交给 DeployStrategy。
"""
from __future__ import annotations

import abc
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class DeployOutcome:
    success: bool
    reason: str = ""  # 失败时的人类可读分类原因
    access_url: str = ""  # 成功时的访问地址


def _run_checked(command: list, cwd: str | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, command, output=result.stdout, stderr=result.stderr
        )
    return result


def _collect_output(exc: subprocess.CalledProcessError) -> str:
    parts = []
    if exc.output:
        parts.append(exc.output.strip())
    if exc.stderr:
        parts.append(exc.stderr.strip())
    return "\n".join(p for p in parts if p).strip()


def _tail_text(text: str, max_lines: int = 20) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _append_build_arg(command: list, arg_name: str, arg_value: str) -> None:
    value = (arg_value or "").strip()
    if value:
        command.extend(["--build-arg", f"{arg_name}={value}"])


class DeployStrategy(abc.ABC):
    """部署策略抽象。子类决定如何构建、启动、健康检查、分类失败。"""

    name: str = "base"

    @abc.abstractmethod
    def deploy(self, target_dir: str, logger: Any) -> DeployOutcome:
        """执行完整部署流程，返回 DeployOutcome。"""


class DockerfileGoStrategy(DeployStrategy):
    """基于单镜像 Go + CGO 的 Dockerfile 部署策略。"""

    name = "docker-go"

    IMAGE_TAG = "demo-app"
    CONTAINER_NAME = "demo-app-container"
    PORT = 8080

    _DEFAULT_DOCKERFILE = (
        "ARG GO_IMAGE=golang:1.22-alpine\n"
        "FROM ${GO_IMAGE}\n\n"
        "ARG ALPINE_MIRROR=\n\n"
        "RUN if [ -n \"$ALPINE_MIRROR\" ]; then \\\n"
        "      sed -i \"s|https://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR}|g\" /etc/apk/repositories; \\\n"
        "    fi\n\n"
        "RUN apk add --no-cache build-base\n\n"
        "ARG GO_PROXY=https://proxy.golang.org,direct\n"
        "ENV GOPROXY=${GO_PROXY}\n\n"
        "WORKDIR /src\n\n"
        "COPY go.mod go.sum ./\n"
        "RUN go mod download\n\n"
        "COPY . .\n\n"
        "RUN CGO_ENABLED=1 GOOS=linux go build -o /out/main .\n\n"
        "WORKDIR /app\n\n"
        "RUN cp /out/main /app/main\n\n"
        "EXPOSE 8080\n\n"
        'CMD ["/app/main"]\n'
    )

    def deploy(self, target_dir: str, logger: Any) -> DeployOutcome:
        self._ensure_dockerfile(target_dir)
        build_command = ["docker", "build", "--pull=false", "-t", self.IMAGE_TAG]
        _append_build_arg(build_command, "GO_IMAGE", os.getenv("LARKFLOW_GO_IMAGE", ""))
        _append_build_arg(build_command, "ALPINE_MIRROR", os.getenv("LARKFLOW_ALPINE_MIRROR", ""))
        _append_build_arg(build_command, "GO_PROXY", os.getenv("LARKFLOW_GO_PROXY", ""))
        build_command.append(".")

        try:
            logger.info("docker build", extra={"event": "docker_build"})
            _run_checked(build_command, cwd=target_dir)

            # 清理旧容器；失败忽略，因为可能根本不存在
            subprocess.run(
                ["docker", "rm", "-f", self.CONTAINER_NAME],
                capture_output=True,
                text=True,
            )

            logger.info("docker run", extra={"event": "docker_run"})
            run_result = _run_checked(
                [
                    "docker", "run", "-d",
                    "--name", self.CONTAINER_NAME,
                    "-p", f"{self.PORT}:{self.PORT}",
                    self.IMAGE_TAG,
                ]
            )
            container_id = run_result.stdout.strip()
            if container_id:
                logger.info(
                    f"container created: {container_id}",
                    extra={"event": "container_created"},
                )

            failure = self._inspect_container_failure()
            if failure:
                return DeployOutcome(success=False, reason=failure)

            return DeployOutcome(success=True, access_url=f"http://localhost:{self.PORT}")

        except subprocess.CalledProcessError as exc:
            cmd = exc.cmd
            stage = " ".join(cmd[:2]) if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 else str(cmd)
            details = _collect_output(exc)
            reason = self._classify_failure(stage, details)
            if details:
                logger.error(_tail_text(details), extra={"event": "deploy_failed_detail"})
            return DeployOutcome(success=False, reason=reason)

    # --- internal helpers -------------------------------------------------

    def _ensure_dockerfile(self, target_dir: str) -> None:
        dockerfile = os.path.join(target_dir, "Dockerfile")
        if not os.path.exists(dockerfile):
            with open(dockerfile, "w", encoding="utf-8") as f:
                f.write(self._DEFAULT_DOCKERFILE)

    def _inspect_container_failure(self) -> str:
        """检查容器是否立即退出；已退出则返回带分类的错误信息。"""
        time.sleep(2)
        inspect = _run_checked(
            ["docker", "inspect", "-f", "{{.State.Status}}", self.CONTAINER_NAME]
        )
        status = inspect.stdout.strip()
        if status == "running":
            return ""

        logs = subprocess.run(
            ["docker", "logs", self.CONTAINER_NAME], capture_output=True, text=True
        )
        log_text = "\n".join(
            p.strip() for p in [logs.stdout, logs.stderr] if p and p.strip()
        )
        reason = self._classify_failure("container health", log_text)
        detail = _tail_text(log_text)
        if detail:
            return f"{reason}\n最近日志:\n{detail}"
        return reason

    def _classify_failure(self, stage: str, details: str) -> str:
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


# ---- Registry ---------------------------------------------------------

_STRATEGIES: Dict[str, DeployStrategy] = {}


def register(strategy: DeployStrategy) -> None:
    _STRATEGIES[strategy.name] = strategy


def get_strategy(name: str | None) -> DeployStrategy:
    """按名取策略；未知名称退回到 docker-go 默认。"""
    if name and name in _STRATEGIES:
        return _STRATEGIES[name]
    return _STRATEGIES["docker-go"]


register(DockerfileGoStrategy())
