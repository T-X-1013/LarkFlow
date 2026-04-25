import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline.start_ingress import app


class StartIngressTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)

    def test_requires_valid_token(self):
        with patch.dict(
            os.environ,
            {"LARK_START_INGRESS_TOKEN": "expected-token"},
            clear=False,
        ):
            response = self.client.post(
                "/lark/start-demand",
                json={"demand_id": "DEMAND-001", "doc_url": "https://example.com"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "unauthorized")

    def test_returns_500_when_token_is_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post(
                "/lark/start-demand",
                headers={"X-LarkFlow-Token": "anything"},
                json={"demand_id": "DEMAND-001", "doc_url": "https://example.com"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            "LARK_START_INGRESS_TOKEN is not configured",
        )

    def test_forwards_payload_to_existing_start_handler(self):
        payload = {
            "demand_id": "DEMAND-INGRESS-001",
            "doc_url": "https://example.feishu.cn/docx/abc",
        }

        with patch.dict(
            os.environ,
            {"LARK_START_INGRESS_TOKEN": "expected-token"},
            clear=False,
        ), patch(
            "pipeline.start_ingress.handle_start_request",
            return_value={"code": 0, "msg": "success"},
        ) as mocked_handler:
            response = self.client.post(
                "/lark/start-demand",
                headers={"X-LarkFlow-Token": "expected-token"},
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"code": 0, "msg": "success"})
        mocked_handler.assert_called_once_with(payload)


if __name__ == "__main__":
    unittest.main()
