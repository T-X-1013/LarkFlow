import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline.lark_interaction import app


class LarkInteractionTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self.temp_dir.name, "lark_event_store.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _signed_headers(self, body_bytes: bytes, encrypt_key: str) -> dict[str, str]:
        timestamp = "1713600000"
        nonce = "nonce-001"
        signature = hashlib.sha256(
            (timestamp + nonce + encrypt_key).encode("utf-8") + body_bytes
        ).hexdigest()
        return {
            "X-Lark-Request-Timestamp": timestamp,
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": signature,
            "Content-Type": "application/json",
        }

    def test_url_verification_accepts_valid_token_without_signature(self):
        payload = {
            "challenge": "challenge-token",
            "type": "url_verification",
            "token": "verify-token",
        }

        with patch.dict(
            os.environ,
            {
                "LARK_VERIFICATION_TOKEN": "verify-token",
                "LARK_EVENT_STORE_PATH": self.store_path,
            },
            clear=False,
        ):
            response = self.client.post("/lark/webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"challenge": "challenge-token"})

    def test_webhook_rejects_invalid_signature(self):
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt-invalid-signature",
                "token": "verify-token",
                "event_type": "card.action.trigger",
            },
            "event": {
                "action": {
                    "value": {
                        "action": "approve",
                        "demand_id": "DEMAND-B5",
                    }
                }
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        with patch.dict(
            os.environ,
            {
                "LARK_VERIFICATION_TOKEN": "verify-token",
                "LARK_ENCRYPT_KEY": "encrypt-key",
                "LARK_EVENT_STORE_PATH": self.store_path,
            },
            clear=False,
        ):
            response = self.client.post(
                "/lark/webhook",
                content=body_bytes,
                headers={
                    "X-Lark-Request-Timestamp": "1713600000",
                    "X-Lark-Request-Nonce": "nonce-001",
                    "X-Lark-Signature": "bad-signature",
                    "Content-Type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("signature verification failed", response.json()["msg"])

    def test_duplicate_event_id_only_resumes_once(self):
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt-duplicate-001",
                "token": "verify-token",
                "event_type": "card.action.trigger",
            },
            "event": {
                "action": {
                    "value": {
                        "action": "approve",
                        "demand_id": "DEMAND-B5",
                    }
                }
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        resume_calls = []

        def immediate_runner(target):
            target()

        def fake_resume_after_approval(demand_id, approved, feedback):
            resume_calls.append((demand_id, approved, feedback))

        with patch.dict(
            os.environ,
            {
                "LARK_VERIFICATION_TOKEN": "verify-token",
                "LARK_ENCRYPT_KEY": "encrypt-key",
                "LARK_EVENT_STORE_PATH": self.store_path,
            },
            clear=False,
        ), patch(
            "pipeline.lark_interaction._launch_background_task",
            side_effect=immediate_runner,
        ), patch(
            "pipeline.engine.resume_after_approval",
            side_effect=fake_resume_after_approval,
        ):
            headers = self._signed_headers(body_bytes, "encrypt-key")
            first_response = self.client.post("/lark/webhook", content=body_bytes, headers=headers)
            second_response = self.client.post("/lark/webhook", content=body_bytes, headers=headers)
            third_response = self.client.post("/lark/webhook", content=body_bytes, headers=headers)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(third_response.status_code, 200)
        self.assertEqual(len(resume_calls), 1)


if __name__ == "__main__":
    unittest.main()
