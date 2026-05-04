"""
飞书云文档读取客户端

负责通过飞书 docx API 读取 docx 文档内容，用于前端「从文档创建 Pipeline」功能。

落地策略：
- 文档类型：docx（新版）
- 内容获取：通过 docx.v1.document.raw_content 接口获取纯文本内容
- wiki 文档：先通过 wiki API 转换为 docx token，再读取内容
- 失败策略：抛 `LarkDocReadError` 异常，由路由层捕获并返回友好错误

凡是 SDK 返回非 0 或网络异常，都包装成 `LarkDocReadError` 抛出。
"""
from __future__ import annotations

import re
from typing import Optional

from lark_oapi.api.docx.v1 import RawContentDocumentRequest
from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest

from pipeline.lark.sdk import get_lark_client


class LarkDocReadError(RuntimeError):
    """读取飞书文档失败时抛出"""


def extract_document_id(doc_url: str) -> Optional[str]:
    """
    从飞书文档 URL 中提取 document_id

    支持的 URL 格式：
    - https://feishu.cn/docx/AbCdEfGhIjKlMn
    - https://[tenant].feishu.cn/docx/AbCdEfGhIjKlMn
    - https://[tenant].feishu.cn/wiki/AbCdEfGhIjKlMn

    @params:
        doc_url: 飞书文档链接

    @return:
        返回 document_id；格式不匹配返回 None
    """
    # 匹配 docx 或 wiki 路径
    pattern = r"docx/([A-Za-z0-9]+)|wiki/([A-Za-z0-9]+)"
    match = re.search(pattern, doc_url)
    if match:
        # group(1) 是 docx 后的 ID，group(2) 是 wiki 后的 ID
        return match.group(1) or match.group(2)
    return None


def _resolve_wiki_obj_token(wiki_token: str) -> str:
    """
    通过 wiki 节点 API 将 wiki token 转换为底层 docx 的 obj_token

    @params:
        wiki_token: 从 wiki 链接中解析出的 token

    @return:
        返回底层 docx 的 obj_token；失败时抛 LarkDocReadError
    """
    client = get_lark_client()
    request = GetNodeSpaceRequest.builder().token(wiki_token).build()
    response = client.wiki.v2.space.get_node(request)

    if not response.success():
        raise LarkDocReadError(
            f"读取 Wiki 节点失败 (Code: {response.code}): {response.msg}"
        )

    node = getattr(response.data, "node", None) if response.data else None
    obj_token = getattr(node, "obj_token", None) if node else None
    if not obj_token:
        raise LarkDocReadError("读取 Wiki 节点失败：无法获取底层的 obj_token")

    return obj_token


def read_feishu_doc(document_id: str, doc_url: str = "") -> dict:
    """
    读取飞书文档内容（支持 docx 和 wiki）

    @params:
        document_id: 文档 ID
        doc_url: 原始文档链接（用于判断是否为 wiki）

    @return:
        返回 {"title": str, "content": str}；失败抛 LarkDocReadError
    """
    # 如果是 wiki 链接，需要先转换为 docx token
    if "/wiki/" in doc_url:
        document_id = _resolve_wiki_obj_token(document_id)

    client = get_lark_client()
    request = RawContentDocumentRequest.builder().document_id(document_id).build()

    try:
        response = client.docx.v1.document.raw_content(request)
    except Exception as exc:
        raise LarkDocReadError(f"读取文档异常：{exc}") from exc

    if not response.success():
        raise LarkDocReadError(f"读取文档失败 (Code: {response.code}): {response.msg}")

    # 获取内容（纯文本）
    content = getattr(response.data, "content", "")
    if not content:
        raise LarkDocReadError("文档内容为空")

    # 从内容中提取标题（第一行）和正文
    lines = content.strip().split("\n")
    title = lines[0].strip() if lines else "未命名需求"
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

    return {"title": title, "content": body}
