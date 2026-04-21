import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import engine
from pipeline.llm_adapter import AgentTurn, ToolCall


class EngineLoopB1TestCase(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[2]
        self.workspace_root = self.repo_root / "LarkFlow"
        self.target_temp_dir = tempfile.TemporaryDirectory(
            prefix="demo-app-engine-test-",
            dir=self.repo_root,
        )
        self.target_dir = Path(self.target_temp_dir.name)
        self.target_dir.mkdir(exist_ok=True)

        self.session_id = "DEMAND-B1-LOOP"
        engine.SESSION_STORE.clear()
        engine.SESSION_STORE[self.session_id] = {
            "provider": "openai",
            "client": object(),
            "history": [],
            "pending_approval": None,
            "provider_state": {},
            "target_dir": str(self.target_dir),
        }

    def tearDown(self):
        engine.SESSION_STORE.clear()
        self.target_temp_dir.cleanup()

    def test_run_agent_loop_supports_workspace_read_and_target_write(self):
        relative_target_dir = Path("..") / self.target_dir.name
        file_path = relative_target_dir / "main.go"

        turns = [
            AgentTurn(
                text_blocks=[],
                tool_calls=[
                    ToolCall(
                        id="tool-read-rule",
                        name="file_editor",
                        arguments={"action": "read", "path": "rules/flow-rule.md"},
                    )
                ],
                finished=False,
                raw_response=None,
            ),
            AgentTurn(
                text_blocks=[],
                tool_calls=[
                    ToolCall(
                        id="tool-write-main",
                        name="file_editor",
                        arguments={
                            "action": "write",
                            "path": str(file_path),
                            "content": "package main\n\nfunc main() {}\n",
                        },
                    )
                ],
                finished=False,
                raw_response=None,
            ),
            AgentTurn(
                text_blocks=[],
                tool_calls=[
                    ToolCall(
                        id="tool-replace-main",
                        name="file_editor",
                        arguments={
                            "action": "replace",
                            "path": str(file_path),
                            "old_content": "func main() {}",
                            "content": 'func main() { println("ok") }',
                        },
                    )
                ],
                finished=False,
                raw_response=None,
            ),
            AgentTurn(
                text_blocks=["phase finished"],
                tool_calls=[],
                finished=True,
                raw_response=None,
            ),
        ]

        def fake_create_turn(session, system_prompt):
            return turns.pop(0)

        with patch.object(engine, "create_turn", side_effect=fake_create_turn):
            completed = engine.run_agent_loop(self.session_id, "test prompt")

        self.assertTrue(completed)
        self.assertEqual(turns, [])

        written_file = self.target_dir / "main.go"
        self.assertTrue(written_file.exists())
        self.assertEqual(
            written_file.read_text(encoding="utf-8"),
            'package main\n\nfunc main() { println("ok") }\n',
        )

        history = engine.SESSION_STORE[self.session_id]["history"]
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["name"], "file_editor")
        self.assertIn("rule", history[0]["content"].lower())
        self.assertIn("Successfully wrote", history[1]["content"])
        self.assertIn("Successfully replaced", history[2]["content"])


if __name__ == "__main__":
    unittest.main()
