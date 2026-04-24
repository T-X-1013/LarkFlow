"""
LarkFlow 飞书云文档读取工具

负责：
1. 从飞书 docx / wiki 链接中解析出文档 token
2. 通过 lark-oapi SDK 调用 wiki 与 docx API 读取纯文本内容
"""

import re
from typing import Optional

from lark_oapi.api.docx.v1 import RawContentDocumentRequest
from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest

from pipeline.utils.lark_sdk import get_lark_client


class LarkDocError(RuntimeError):
    """读取飞书文档失败时抛出"""


def extract_doc_token(url: str) -> Optional[str]:
    """
    从飞书文档链接中提取 token

    @params:
        url: 飞书 docx 或 wiki 文档链接

    @return:
        命中时返回链接中的文档 token，否则返回 None
    """
    if not url:
        return None

    match = re.search(r"/docx/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)

    match = re.search(r"/wiki/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)

    return None


def _resolve_wiki_obj_token(wiki_token: str) -> str:
    """
    通过 wiki 节点 API 将 wiki token 转换为底层 docx 的 obj_token

    @params:
        wiki_token: 从 wiki 链接中解析出的 token

    @return:
        返回底层 docx 的 obj_token；失败时抛 LarkDocError
    """
    client = get_lark_client()
    request = GetNodeSpaceRequest.builder().token(wiki_token).build()
    response = client.wiki.v2.space.get_node(request)

    if not response.success():
        raise LarkDocError(
            f"读取 Wiki 节点失败 (Code: {response.code}): {response.msg}。"
            "请确保已在飞书文档右上角将应用（LarkFlow 引擎）添加为协作者"
        )

    node = getattr(response.data, "node", None) if response.data else None
    obj_token = getattr(node, "obj_token", None) if node else None
    if not obj_token:
        raise LarkDocError("读取 Wiki 节点失败：无法获取底层的 obj_token")

    return obj_token


def fetch_lark_doc_content(url: str) -> str:
    """
    读取飞书云文档（docx）和 Wiki 的纯文本内容

    @params:
        url: 飞书 docx 或 wiki 文档链接

    @return:
        成功返回纯文本内容；失败时抛 LarkDocError
    """
    token = extract_doc_token(url)
    if not token:
        raise LarkDocError(
            f"无法从链接 {url} 中提取文档 token，请确保是有效的飞书 docx 或 wiki 链接"
        )

    if "/wiki/" in url:
        token = _resolve_wiki_obj_token(token)

    client = get_lark_client()
    request = RawContentDocumentRequest.builder().document_id(token).build()
    response = client.docx.v1.document.raw_content(request)

    if not response.success():
        raise LarkDocError(
            f"读取飞书文档失败 (Code: {response.code}): {response.msg}"
        )

    return getattr(response.data, "content", "") or ""
