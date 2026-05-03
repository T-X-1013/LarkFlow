"""
`pipeline.lark.doc_client` 单元测试

覆盖通过飞书 import_task 把 markdown 转 docx 的主链路：
1. create_tech_doc: upload_all → import_task.create → import_task.get 轮询
2. grant_doc_access: 默认参数 + 失败抛 LarkDocWriteError
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pipeline.lark import doc_client as lark_doc_client
from pipeline.lark.doc_client import (
    LarkDocWriteError,
    create_tech_doc,
    grant_doc_access,
)


def _ok_response(data) -> MagicMock:
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = data
    return resp


def _err_response(code: int, msg: str) -> MagicMock:
    resp = MagicMock()
    resp.success.return_value = False
    resp.code = code
    resp.msg = msg
    return resp


def _fake_client_ok(
    file_token: str = "boxbcfile123",
    ticket: str = "ticket_abc",
    document_id: str = "docx_token_xyz",
    doc_url: str = "https://feishu.cn/docx/docx_token_xyz",
    get_responses=None,
):
    """构造一个「上传 + 建导入任务 + 轮询成功」的假 SDK client"""
    client = MagicMock()

    client.drive.v1.media.upload_all.return_value = _ok_response(
        SimpleNamespace(file_token=file_token)
    )
    client.drive.v1.import_task.create.return_value = _ok_response(
        SimpleNamespace(ticket=ticket)
    )

    if get_responses is None:
        get_responses = [
            _ok_response(
                SimpleNamespace(
                    result=SimpleNamespace(
                        job_status=0, token=document_id, url=doc_url, job_error_msg=None
                    )
                )
            )
        ]
    client.drive.v1.import_task.get.side_effect = list(get_responses)

    client.drive.v1.permission_member.create.return_value = _ok_response(None)
    return client


class CreateTechDocTestCase(unittest.TestCase):
    def test_happy_path_uploads_imports_and_returns_url(self):
        client = _fake_client_ok()
        with patch.object(lark_doc_client, "get_lark_client", return_value=client), \
             patch.object(lark_doc_client, "time") as fake_time:
            fake_time.sleep = MagicMock()
            document_id, url = create_tech_doc(
                "技术方案 - DEMAND_1", "# 标题\n\n正文", folder_token="fldXYZ"
            )

        self.assertEqual(document_id, "docx_token_xyz")
        self.assertEqual(url, "https://feishu.cn/docx/docx_token_xyz")

        # 上传素材：文件名带 .md，parent_node == folder_token
        upload_call = client.drive.v1.media.upload_all.call_args.args[0]
        body = upload_call.request_body
        self.assertEqual(body.file_name, "技术方案 - DEMAND_1.md")
        self.assertEqual(body.parent_type, "ccm_import_open")
        self.assertEqual(body.parent_node, "fldXYZ")
        self.assertGreater(body.size, 0)
        self.assertIn("docx", body.extra)

        # 导入任务：mount_key 透传 folder_token，type=docx, file_extension=md
        import_call = client.drive.v1.import_task.create.call_args.args[0]
        task = import_call.request_body
        self.assertEqual(task.file_extension, "md")
        self.assertEqual(task.file_token, "boxbcfile123")
        self.assertEqual(task.type, "docx")
        self.assertEqual(task.point.mount_key, "fldXYZ")

    def test_polls_until_success(self):
        get_responses = [
            _ok_response(
                SimpleNamespace(result=SimpleNamespace(job_status=1, token=None, url=None))
            ),
            _ok_response(
                SimpleNamespace(result=SimpleNamespace(job_status=2, token=None, url=None))
            ),
            _ok_response(
                SimpleNamespace(
                    result=SimpleNamespace(
                        job_status=0, token="docx_poll", url="https://feishu.cn/docx/docx_poll"
                    )
                )
            ),
        ]
        client = _fake_client_ok(get_responses=get_responses)

        with patch.object(lark_doc_client, "get_lark_client", return_value=client), \
             patch.object(lark_doc_client, "time") as fake_time:
            fake_time.sleep = MagicMock()
            document_id, url = create_tech_doc("t", "body")

        self.assertEqual(document_id, "docx_poll")
        self.assertEqual(url, "https://feishu.cn/docx/docx_poll")
        self.assertEqual(client.drive.v1.import_task.get.call_count, 3)
        self.assertEqual(fake_time.sleep.call_count, 2)  # 成功那次不再 sleep

    def test_folder_token_falls_back_to_env(self):
        client = _fake_client_ok()
        with patch.object(lark_doc_client, "get_lark_client", return_value=client), \
             patch.object(lark_doc_client, "time") as fake_time, \
             patch.dict(os.environ, {"LARK_TECH_DOC_FOLDER_TOKEN": "fld_from_env"}):
            fake_time.sleep = MagicMock()
            create_tech_doc("t", "body")

        upload_call = client.drive.v1.media.upload_all.call_args.args[0]
        self.assertEqual(upload_call.request_body.parent_node, "fld_from_env")
        import_call = client.drive.v1.import_task.create.call_args.args[0]
        self.assertEqual(import_call.request_body.point.mount_key, "fld_from_env")

    def test_no_folder_falls_back_to_root(self):
        client = _fake_client_ok()
        with patch.object(lark_doc_client, "get_lark_client", return_value=client), \
             patch.object(lark_doc_client, "time") as fake_time, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LARK_TECH_DOC_FOLDER_TOKEN", None)
            fake_time.sleep = MagicMock()
            create_tech_doc("t", "body")

        upload_call = client.drive.v1.media.upload_all.call_args.args[0]
        self.assertEqual(upload_call.request_body.parent_node, "")

    def test_upload_failure_raises(self):
        client = MagicMock()
        client.drive.v1.media.upload_all.return_value = _err_response(1254001, "forbidden")

        with patch.object(lark_doc_client, "get_lark_client", return_value=client):
            with self.assertRaises(LarkDocWriteError) as ctx:
                create_tech_doc("t", "body")
        self.assertIn("1254001", str(ctx.exception))

    def test_import_task_job_failure_raises(self):
        fail_resp = _ok_response(
            SimpleNamespace(
                result=SimpleNamespace(
                    job_status=9, token=None, url=None, job_error_msg="parse error"
                )
            )
        )
        client = _fake_client_ok(get_responses=[fail_resp])

        with patch.object(lark_doc_client, "get_lark_client", return_value=client), \
             patch.object(lark_doc_client, "time") as fake_time:
            fake_time.sleep = MagicMock()
            with self.assertRaises(LarkDocWriteError) as ctx:
                create_tech_doc("t", "body")
        self.assertIn("parse error", str(ctx.exception))

    def test_poll_timeout_raises(self):
        in_progress = _ok_response(
            SimpleNamespace(result=SimpleNamespace(job_status=1, token=None, url=None))
        )
        client = _fake_client_ok(get_responses=[in_progress] * 50)

        with patch.object(lark_doc_client, "get_lark_client", return_value=client), \
             patch.object(lark_doc_client, "time") as fake_time, \
             patch.object(lark_doc_client, "_POLL_MAX_ATTEMPTS", 3):
            fake_time.sleep = MagicMock()
            with self.assertRaises(LarkDocWriteError) as ctx:
                create_tech_doc("t", "body")
        self.assertIn("超时", str(ctx.exception))

    def test_sdk_exception_wrapped(self):
        client = MagicMock()
        client.drive.v1.media.upload_all.side_effect = RuntimeError("boom")

        with patch.object(lark_doc_client, "get_lark_client", return_value=client):
            with self.assertRaises(LarkDocWriteError) as ctx:
                create_tech_doc("t", "body")
        self.assertIn("boom", str(ctx.exception))


class GrantDocAccessTestCase(unittest.TestCase):
    def test_default_params_build_request(self):
        client = MagicMock()
        client.drive.v1.permission_member.create.return_value = _ok_response(None)

        with patch.object(lark_doc_client, "get_lark_client", return_value=client):
            grant_doc_access("docx_123", "oc_chat_abc")

        call = client.drive.v1.permission_member.create.call_args.args[0]
        self.assertEqual(call.token, "docx_123")
        self.assertEqual(call.type, "docx")
        self.assertFalse(call.need_notification)
        body = call.request_body
        self.assertEqual(body.member_type, "openchat")
        self.assertEqual(body.member_id, "oc_chat_abc")
        self.assertEqual(body.perm, "view")

    def test_missing_params_raises(self):
        with self.assertRaises(LarkDocWriteError):
            grant_doc_access("", "oc_xxx")
        with self.assertRaises(LarkDocWriteError):
            grant_doc_access("docx_1", "")

    def test_failure_raises(self):
        client = MagicMock()
        client.drive.v1.permission_member.create.return_value = _err_response(99999, "nope")

        with patch.object(lark_doc_client, "get_lark_client", return_value=client):
            with self.assertRaises(LarkDocWriteError) as ctx:
                grant_doc_access("docx_1", "oc_xxx")
        self.assertIn("99999", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
