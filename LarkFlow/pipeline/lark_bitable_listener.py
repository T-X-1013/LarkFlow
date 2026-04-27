"""
LarkFlow 多维表格（Base）事件监听

负责方案 B 的入向链路：
1. 进程启动时向飞书订阅目标 Base 的文件事件（幂等）
2. 收到 bitable_record_changed 事件后，按 table_id 过滤
3. 读取记录的当前字段值，状态列为空或「待启动」时，按 env 配置的 target + receive_id_type 发卡
4. 发卡后回写状态列为「已发卡」，作为去重标记；异常时回写「失败」

接收方通过两个 env 决定：
  - LARK_DEMAND_APPROVE_TARGET：chat_id 或 open_id 字符串
  - LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE：chat_id / open_id，默认 open_id

所有状态变更都走 Base 状态列，避免额外依赖 DB 做幂等；事件重复投递时，
状态列已变就天然跳过。
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Optional

from lark_oapi.api.bitable.v1 import (
    AppTableRecord,
    GetAppTableRecordRequest,
    UpdateAppTableRecordRequest,
)
from lark_oapi.api.drive.v1 import SubscribeFileRequest
from lark_oapi.api.drive.v1 import P2DriveFileBitableRecordChangedV1

from pipeline.lark_client import send_demand_start_card
from pipeline.utils.lark_sdk import get_lark_client


STATUS_EMPTY = ""
STATUS_PENDING = "待启动"
STATUS_CARD_SENT = "已发卡"
STATUS_PROCESSING = "处理中"
STATUS_STARTED = "已启动"
STATUS_REJECTED = "驳回"
STATUS_FAILED = "失败"

# 状态列处于这些值时，事件到达会重新发卡；其它值一律跳过
_TRIGGER_STATUSES = {STATUS_EMPTY, STATUS_PENDING}

# 记录已被删除 / 事件延迟投递导致 record_id 找不到；这是正常场景，静默跳过
_ERR_RECORD_NOT_FOUND = 1254043


def _demand_base_token() -> str:
    return (os.getenv("LARK_DEMAND_BASE_TOKEN") or "").strip()


def _demand_table_id() -> str:
    return (os.getenv("LARK_DEMAND_TABLE_ID") or "").strip()


def _demand_status_field() -> str:
    return (os.getenv("LARK_DEMAND_STATUS_FIELD") or "状态").strip()


def _demand_id_field() -> str:
    return (os.getenv("LARK_DEMAND_ID_FIELD") or "需求ID").strip()


def _demand_doc_field() -> str:
    return (os.getenv("LARK_DEMAND_DOC_FIELD") or "需求文档").strip()


def _tech_doc_field() -> str:
    return (os.getenv("LARK_TECH_DOC_FIELD") or "技术方案文档").strip()


def _approve_target() -> str:
    return (os.getenv("LARK_DEMAND_APPROVE_TARGET") or "").strip()


def _approve_receive_id_type() -> str:
    return (os.getenv("LARK_DEMAND_APPROVE_RECEIVE_ID_TYPE") or "open_id").strip()


def subscribe_demand_base() -> None:
    """
    向飞书订阅需求 Base 的文件事件；接口幂等，重复调用不会报错

    @params:
        无入参

    @return:
        无返回值；订阅失败会打印日志但不抛异常，避免拖垮 WS 启动
    """
    file_token = _demand_base_token()
    if not file_token:
        print("[BitableListener] 未配置 LARK_DEMAND_BASE_TOKEN，跳过订阅")
        return

    request = (
        SubscribeFileRequest.builder()
        .file_token(file_token)
        .file_type("bitable")
        .build()
    )

    try:
        response = get_lark_client().drive.v1.file.subscribe(request)
    except Exception as exc:  # noqa: BLE001  SDK 可能抛网络异常
        print(f"[BitableListener] 订阅 Base 失败（异常）: {exc}")
        return

    if not response.success():
        print(
            f"[BitableListener] 订阅 Base 失败: code={response.code} msg={response.msg}"
        )
        return

    print(f"[BitableListener] 已订阅 Base 事件: file_token={file_token}")


def _extract_plain_text(field_value: Any) -> str:
    """
    把 Base 字段值拍扁成字符串；兼容富文本 list / 链接 dict / 纯文本

    @params:
        field_value: Base 记录字段的原始值（SDK 返回可能是 str/list/dict）

    @return:
        返回用于后续逻辑的纯字符串表达；解析失败时返回 str(field_value)
    """
    if field_value is None:
        return ""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        parts: list[str] = []
        for item in field_value:
            if isinstance(item, dict):
                parts.append(
                    item.get("link")
                    or item.get("text")
                    or item.get("name")
                    or ""
                )
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    if isinstance(field_value, dict):
        return str(
            field_value.get("link")
            or field_value.get("text")
            or field_value.get("name")
            or field_value
        )
    return str(field_value)


def _get_record_fields(record_id: str) -> Optional[dict[str, Any]]:
    """
    读取指定记录的字段 dict；不存在或异常时返回 None

    @params:
        record_id: 需求行 record_id

    @return:
        返回 {字段名: 字段值}；异常时返回 None
    """
    request = (
        GetAppTableRecordRequest.builder()
        .app_token(_demand_base_token())
        .table_id(_demand_table_id())
        .record_id(record_id)
        .build()
    )

    try:
        response = get_lark_client().bitable.v1.app_table_record.get(request)
    except Exception as exc:  # noqa: BLE001
        print(f"[BitableListener] 读取记录 {record_id} 异常: {exc}")
        return None

    if not response.success():
        # 记录已删除或事件延迟投递时 code=1254043，是常见无害场景，静默跳过
        if response.code != _ERR_RECORD_NOT_FOUND:
            print(
                f"[BitableListener] 读取记录 {record_id} 失败: code={response.code} msg={response.msg}"
            )
        return None

    data = response.data
    record = getattr(data, "record", None) if data else None
    return getattr(record, "fields", None) or {}


def update_demand_status(record_id: str, status: str) -> bool:
    """
    把指定记录的状态列回写成目标值

    @params:
        record_id: 需求行 record_id
        status: 要写入的状态值（必须是 Base 状态列的合法单选项）

    @return:
        成功返回 True；失败返回 False 并打印日志
    """
    body = AppTableRecord.builder().fields({_demand_status_field(): status}).build()
    request = (
        UpdateAppTableRecordRequest.builder()
        .app_token(_demand_base_token())
        .table_id(_demand_table_id())
        .record_id(record_id)
        .request_body(body)
        .build()
    )

    try:
        response = get_lark_client().bitable.v1.app_table_record.update(request)
    except Exception as exc:  # noqa: BLE001
        print(f"[BitableListener] 回写状态异常 record={record_id} status={status}: {exc}")
        return False

    if not response.success():
        print(
            f"[BitableListener] 回写状态失败 record={record_id} status={status}: "
            f"code={response.code} msg={response.msg}"
        )
        return False

    return True


def update_demand_tech_doc_url(record_id: str, url: str) -> bool:
    """
    把技术方案文档链接回写到 Base 的技术方案文档列

    @params:
        record_id: 需求行 record_id
        url: 飞书云文档 url（docx）

    @return:
        成功返回 True；失败返回 False 并打印日志
    """
    if not record_id or not url:
        return False

    field_name = _tech_doc_field()
    # URL 类型字段需要 {"text": <显示名>, "link": <url>} 的对象结构
    field_value = {"text": url, "link": url}
    body = AppTableRecord.builder().fields({field_name: field_value}).build()
    request = (
        UpdateAppTableRecordRequest.builder()
        .app_token(_demand_base_token())
        .table_id(_demand_table_id())
        .record_id(record_id)
        .request_body(body)
        .build()
    )

    try:
        response = get_lark_client().bitable.v1.app_table_record.update(request)
    except Exception as exc:  # noqa: BLE001
        print(f"[BitableListener] 回写技术方案链接异常 record={record_id}: {exc}")
        return False

    if not response.success():
        print(
            f"[BitableListener] 回写技术方案链接失败 record={record_id}: "
            f"code={response.code} msg={response.msg}"
        )
        return False

    return True


def _process_record(record_id: str) -> None:
    """
    针对单条记录执行「读取 → 判断状态 → 发卡 → 回写」逻辑

    @params:
        record_id: 需求行 record_id

    @return:
        无返回值；所有异常路径都会把状态回写为「失败」（若能写到）
    """
    fields = _get_record_fields(record_id)
    if fields is None:
        return

    status_raw = _extract_plain_text(fields.get(_demand_status_field()))
    if status_raw not in _TRIGGER_STATUSES:
        # 已发卡 / 处理中 / 已启动 / 驳回 / 失败 都不再重复发卡
        return

    doc_url = _extract_plain_text(fields.get(_demand_doc_field()))
    if not doc_url:
        # 新增行时字段往往还没填完：需求文档作为"完成信号"，没填就静默等下次事件
        print(f"[BitableListener] 记录 {record_id} 尚未填写需求文档，等待后续编辑事件")
        return

    demand_id = _extract_plain_text(fields.get(_demand_id_field()))
    if not demand_id:
        # 自增编号字段有时滞后一点，用 record_id 兜底
        demand_id = record_id

    target = _approve_target()
    receive_id_type = _approve_receive_id_type()
    if not target:
        print(
            "[BitableListener] 未配置 LARK_DEMAND_APPROVE_TARGET，无法发卡"
        )
        update_demand_status(record_id, STATUS_FAILED)
        return

    try:
        result = send_demand_start_card(
            target=target,
            demand_id=demand_id,
            doc_url=doc_url,
            base_token=_demand_base_token(),
            table_id=_demand_table_id(),
            record_id=record_id,
            receive_id_type=receive_id_type,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[BitableListener] 发卡异常 record={record_id}: {exc}")
        traceback.print_exc()
        update_demand_status(record_id, STATUS_FAILED)
        return

    if result.get("code") != 0:
        print(f"[BitableListener] 发卡失败 record={record_id}: {result}")
        update_demand_status(record_id, STATUS_FAILED)
        return

    if not update_demand_status(record_id, STATUS_CARD_SENT):
        # 卡片已发出但状态回写失败：下次事件还会再发一张，靠人工介入兜底
        print(
            f"[BitableListener] 卡片已发送但状态回写失败 record={record_id}，"
            f"下次事件重推会再次触发发卡"
        )
        return

    print(
        f"[BitableListener] 已发卡 record={record_id} demand_id={demand_id} "
        f"target={target} type={receive_id_type}"
    )


def on_record_changed(event: P2DriveFileBitableRecordChangedV1) -> None:
    """
    bitable_record_changed 事件的业务回调

    @params:
        event: SDK 解析好的事件对象

    @return:
        无返回值；所有异常均在内部处理，避免把 WS 监听循环打断
    """
    data = event.event if event else None
    if not data:
        print("[BitableListener] 收到事件但 data 为空，跳过")
        return

    print(
        f"[BitableListener] 事件到达: file_token={data.file_token} "
        f"table_id={data.table_id} actions={len(data.action_list or [])}"
    )

    if data.file_token and data.file_token != _demand_base_token():
        print(
            f"[BitableListener] file_token 不匹配 (期望 {_demand_base_token()})，跳过"
        )
        return

    if data.table_id and data.table_id != _demand_table_id():
        print(
            f"[BitableListener] table_id 不匹配 (期望 {_demand_table_id()})，跳过"
        )
        return

    for action in data.action_list or []:
        record_id = getattr(action, "record_id", None)
        if not record_id:
            continue
        try:
            _process_record(record_id)
        except Exception as exc:  # noqa: BLE001  兜底避免打断事件循环
            print(f"[BitableListener] 处理记录 {record_id} 异常: {exc}")
            traceback.print_exc()
