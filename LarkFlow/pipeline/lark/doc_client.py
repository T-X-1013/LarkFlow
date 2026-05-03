"""
LarkFlow 飞书云文档写入客户端

负责 Phase 1 审批链路中"把技术方案产物落成一篇飞书 docx + 授权给审批人"的两个原子动作：
1. create_tech_doc:  上传 markdown 素材 → 调用飞书「导入任务」转成 docx → 轮询拿到文档 token
2. grant_doc_access: 把 docx 共享给指定成员 / 群 / 部门

落地策略：
- 文档类型: docx（新版）
- 内容写入: 通过飞书原生 import_task 把 markdown 直接转成 docx，标题/列表/代码块/表格/图片按原生渲染
- 失败策略: 抛异常，由调用方降级

凡是 SDK 返回非 0 或网络异常，都包装成 `LarkDocWriteError` 抛出，
让 engine 层可以 try/except 做降级，不影响审批链路可用性。
"""

from __future__ import annotations

import io
import json
import os
import time
from typing import Optional

from lark_oapi.api.drive.v1 import (
    BaseMember,
    CreateImportTaskRequest,
    CreatePermissionMemberRequest,
    GetImportTaskRequest,
    ImportTask,
    ImportTaskMountPoint,
    UploadAllMediaRequest,
    UploadAllMediaRequestBody,
)

from pipeline.lark.sdk import get_lark_client


class LarkDocWriteError(RuntimeError):
    """新建飞书文档 / 授权失败时抛出；engine 层捕获即可降级为截断卡"""


_DEFAULT_DOC_DOMAIN = "https://feishu.cn"

# import_task job_status: 0 成功；1/2 处理中；其余视为失败（见飞书开放平台文档）
_IMPORT_STATUS_SUCCESS = 0
_IMPORT_STATUS_IN_PROGRESS = {1, 2}

# 轮询默认参数；测试可通过 monkeypatch 缩短
_POLL_MAX_ATTEMPTS = 30
_POLL_INTERVAL_SEC = 1.0

# mount_type = 1 表示挂载到「我的空间」/ 指定文件夹；mount_key 为 folder_token，空串表示根目录
_MOUNT_TYPE_FOLDER = 1


def _doc_domain() -> str:
    return (os.getenv("LARK_DOC_DOMAIN") or _DEFAULT_DOC_DOMAIN).rstrip("/")


def _folder_token() -> Optional[str]:
    token = (os.getenv("LARK_TECH_DOC_FOLDER_TOKEN") or "").strip()
    return token or None


def _upload_markdown(file_name: str, content: str, parent_node: str) -> str:
    """
    用 drive.media.upload_all 把 markdown 作为导入素材上传

    @params:
        file_name: 上传文件名，需包含 .md 后缀
        content: markdown 正文
        parent_node: 导入目标文件夹 token；根目录传空串

    @return:
        素材 file_token，用于创建 import_task
    """
    payload = (content or "").encode("utf-8")
    extra = json.dumps({"obj_type": "docx", "file_extension": "md"})

    body = (
        UploadAllMediaRequestBody.builder()
        .file_name(file_name)
        .parent_type("ccm_import_open")
        .parent_node(parent_node)
        .size(len(payload))
        .extra(extra)
        .file(io.BytesIO(payload))
        .build()
    )
    request = UploadAllMediaRequest.builder().request_body(body).build()

    client = get_lark_client()
    try:
        response = client.drive.v1.media.upload_all(request)
    except Exception as exc:  # noqa: BLE001
        raise LarkDocWriteError(f"上传 markdown 素材异常: {exc}") from exc

    if not response.success():
        raise LarkDocWriteError(
            f"上传 markdown 素材失败 (Code: {response.code}): {response.msg}"
        )

    file_token = getattr(response.data, "file_token", None) if response.data else None
    if not file_token:
        raise LarkDocWriteError("上传 markdown 素材成功但响应缺少 file_token")
    return file_token


def _create_import_task(
    file_token: str, file_name: str, mount_key: str
) -> str:
    """
    触发 markdown → docx 导入任务，返回 ticket 供后续轮询
    """
    task = (
        ImportTask.builder()
        .file_extension("md")
        .file_token(file_token)
        .type("docx")
        .file_name(file_name)
        .point(
            ImportTaskMountPoint.builder()
            .mount_type(_MOUNT_TYPE_FOLDER)
            .mount_key(mount_key)
            .build()
        )
        .build()
    )
    request = CreateImportTaskRequest.builder().request_body(task).build()

    client = get_lark_client()
    try:
        response = client.drive.v1.import_task.create(request)
    except Exception as exc:  # noqa: BLE001
        raise LarkDocWriteError(f"创建导入任务异常: {exc}") from exc

    if not response.success():
        raise LarkDocWriteError(
            f"创建导入任务失败 (Code: {response.code}): {response.msg}"
        )

    ticket = getattr(response.data, "ticket", None) if response.data else None
    if not ticket:
        raise LarkDocWriteError("创建导入任务成功但响应缺少 ticket")
    return ticket


def _poll_import_task(ticket: str) -> tuple[str, Optional[str]]:
    """
    轮询导入任务直到成功/失败/超时，返回 (docx_token, docx_url)
    """
    client = get_lark_client()
    request = GetImportTaskRequest.builder().ticket(ticket).build()

    for _ in range(_POLL_MAX_ATTEMPTS):
        try:
            response = client.drive.v1.import_task.get(request)
        except Exception as exc:  # noqa: BLE001
            raise LarkDocWriteError(f"查询导入任务异常: {exc}") from exc

        if not response.success():
            raise LarkDocWriteError(
                f"查询导入任务失败 (Code: {response.code}): {response.msg}"
            )

        result = getattr(response.data, "result", None) if response.data else None
        status = getattr(result, "job_status", None) if result else None

        if status == _IMPORT_STATUS_SUCCESS:
            token = getattr(result, "token", None)
            url = getattr(result, "url", None)
            if not token:
                raise LarkDocWriteError("导入任务成功但响应缺少文档 token")
            return token, url

        if status not in _IMPORT_STATUS_IN_PROGRESS:
            err_msg = getattr(result, "job_error_msg", None) if result else None
            raise LarkDocWriteError(
                f"导入任务失败 (job_status={status}): {err_msg or '未知错误'}"
            )

        time.sleep(_POLL_INTERVAL_SEC)

    raise LarkDocWriteError(
        f"导入任务轮询超时 ({_POLL_MAX_ATTEMPTS} 次仍未完成)"
    )


def create_tech_doc(
    title: str,
    content_markdown: str,
    folder_token: Optional[str] = None,
) -> tuple[str, str]:
    """
    通过飞书「导入任务」把 markdown 转成一篇 docx，并返回 (document_id, doc_url)

    @params:
        title: 文档标题；同时作为上传素材和导入任务的 file_name 前缀
        content_markdown: 文档正文 markdown；允许为空（生成空文档）
        folder_token: 可选父文件夹 token；为空时读取 LARK_TECH_DOC_FOLDER_TOKEN，仍为空则落根目录

    @return:
        (document_id, doc_url) 二元组；失败抛 LarkDocWriteError
    """
    safe_title = title or "未命名技术方案"
    parent = folder_token if folder_token is not None else _folder_token()
    mount_key = parent or ""

    file_token = _upload_markdown(
        file_name=f"{safe_title}.md",
        content=content_markdown or "",
        parent_node=mount_key,
    )
    ticket = _create_import_task(
        file_token=file_token, file_name=safe_title, mount_key=mount_key
    )
    document_id, url = _poll_import_task(ticket)

    if not url:
        url = f"{_doc_domain()}/docx/{document_id}"
    return document_id, url


def grant_doc_access(
    document_id: str,
    member_id: str,
    member_type: str = "openchat",
    perm: str = "view",
    need_notification: bool = False,
) -> None:
    """
    把 docx 分享给指定成员（用户 / 群 / 部门）

    @params:
        document_id: 目标 docx 的 id
        member_id: 成员标识；member_type=openchat 时传 chat_id，openid 时传 open_id
        member_type: 成员类型，常用值 openchat / openid / departmentid，默认 openchat
        perm: 权限级别，常用 view / edit / full_access，默认 view
        need_notification: 是否给成员发通知，默认 False 避免打扰

    @return:
        无返回值；失败抛 LarkDocWriteError
    """
    if not document_id or not member_id:
        raise LarkDocWriteError("grant_doc_access 缺少必要参数: document_id / member_id")

    body = (
        BaseMember.builder()
        .member_type(member_type)
        .member_id(member_id)
        .perm(perm)
        .build()
    )
    request = (
        CreatePermissionMemberRequest.builder()
        .token(document_id)
        .type("docx")
        .need_notification(need_notification)
        .request_body(body)
        .build()
    )

    client = get_lark_client()
    try:
        response = client.drive.v1.permission_member.create(request)
    except Exception as exc:  # noqa: BLE001
        raise LarkDocWriteError(f"授权飞书文档异常: {exc}") from exc

    if not response.success():
        raise LarkDocWriteError(
            f"授权飞书文档失败 (Code: {response.code}): {response.msg}"
        )
