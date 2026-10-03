"""U148 REPLAN: Antigravity's hook never writes the user desk; only the explicit registration does.

Receipt (Codex codex_u148_c1_human_origin_gate_unmet, 2026-10-04): invocationNum 0, a desktop-app conversation and a
present or missing prompt do not prove that a human turned this conversation into the user's desk; automatic
continuations, restarts and subagents produce the same payload. Until a verified human-origin field exists, the hook
only reads an existing registration and keeps the payload's key names as evidence. Rules under test:
1. No PreInvocation payload registers or repairs a desk: missing prompt, missing invocationNum, a restart of the same
   conversation, an automatic continuation, a subagent conversation, or an INVALID existing record.
2. `coord presence --desk-thread` (desktop-app ids only) is the one way to set or repair the desk.
3. In a desktop conversation with no valid desk, the hook line tells the Antigravity model how to register this
   conversation, and only for when 윤겸스 is the one typing; a valid desk elsewhere or a CLI conversation hears nothing.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import board, deliver, hook_context

DESK = "2c573cc3-3c50-40a7-a060-738cadce9bc5"
CLI_ONLY = "ae1af179-2b66-4d63-a286-3dc22c4ddecd"
SUBAGENT = "0199cccc-0000-4000-8000-000000000004"


class HookRegistersNothingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.project = base / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        app = base / "agy-app"
        (app / "conversations").mkdir(parents=True)
        (app / "conversations" / f"{DESK}.db").write_bytes(b"")
        (app / "brain" / SUBAGENT).mkdir(parents=True)
        env = {deliver.AGY_APP_HOME_ENV: str(app), board.OLLA_USAGE_ENV: str(base / "olla.jsonl"),
               board.AGY_BRAIN_ENV: str(base / "no-brain"), board.CLAUDE_PROJECTS_ENV: str(base / "no-claude")}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        os.environ.pop("UAOS_WORKER", None)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _hook(self, payload):
        from v7_harness.cli import main as cli_main

        event = json.dumps({"workspacePaths": [str(self.project)], **payload})
        argv = ["coord", "presence", "--tool", "antigravity", "--state", "ACTIVE", "--ttl", "3600", "--from-hook",
                "--say", "agy", "--delta", "--project", str(self.project)]
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(event)), contextlib.redirect_stdout(out):
            cli_main(argv)
        (self.project / hook_context.AGY_SEEN).unlink(missing_ok=True)  # each call speaks (U95-A once-per-change)
        text = out.getvalue().strip()
        return json.loads(text)["injectSteps"][0]["ephemeralMessage"] if text.startswith('{"inject') else ""

    def _explicit(self, thread):
        from v7_harness.cli import main as cli_main

        with contextlib.redirect_stdout(io.StringIO()):
            return cli_main(["coord", "presence", "--tool", "antigravity", "--desk-thread", thread,
                             "--project", str(self.project)])

    def _state(self):
        return deliver.user_desk_state(self.project, "antigravity")

    def test_no_payload_registers_a_desk(self):
        payloads = [
            {"conversationId": DESK, "invocationNum": 0},  # missing prompt
            {"conversationId": DESK},  # missing invocationNum
            {"conversationId": DESK, "invocationNum": 0, "userPrompt": "윤겸스가 직접 쓴 지시"},  # looks human
            {"conversationId": DESK, "invocationNum": 0},  # restart of the same conversation
            {"conversationId": DESK, "invocationNum": 0, "prompt": "Continue"},  # automatic continuation
            {"conversationId": SUBAGENT, "invocationNum": 0, "prompt": "Review the diff"},  # subagent conversation
        ]
        for payload in payloads:
            self._hook(payload)
            self.assertEqual(self._state(), ("ABSENT", ""), payload)
        keys = json.loads((self.project / ".coord" / "presence" / "agy_hook_keys.json").read_text(encoding="utf-8"))
        self.assertEqual(keys, ["conversationId", "invocationNum", "prompt", "workspacePaths"])  # names, never values

    def test_an_invalid_record_stays_invalid_until_explicit_registration(self):
        path = deliver.user_desk_path(self.project, "antigravity")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        self._hook({"conversationId": DESK, "invocationNum": 0})
        self.assertEqual(self._state(), ("INVALID", ""))
        self.assertEqual(self._explicit(CLI_ONLY), 2)
        self.assertEqual(self._state(), ("INVALID", ""))
        self.assertEqual(self._explicit(DESK), 0)
        self.assertEqual(self._state(), ("OK", DESK))

    def test_an_existing_desk_is_read_and_never_rewritten(self):
        self.assertEqual(self._explicit(DESK), 0)
        before = deliver.user_desk_path(self.project, "antigravity").read_bytes()
        self._hook({"conversationId": SUBAGENT, "invocationNum": 0, "userPrompt": "윤겸스가 직접 쓴 지시"})
        self._hook({"conversationId": DESK, "invocationNum": 0})
        self.assertEqual(deliver.user_desk_path(self.project, "antigravity").read_bytes(), before)

    def test_without_a_valid_desk_the_model_is_told_how_to_register(self):
        line = self._hook({"conversationId": DESK, "invocationNum": 0})
        self.assertIn(f"--desk-thread {DESK}", line)
        self.assertIn("윤겸스", line)  # only when the user is the one typing in this conversation
        self.assertNotIn("--desk-thread", self._hook({"conversationId": CLI_ONLY, "invocationNum": 0}))
        self.assertNotIn("--desk-thread", self._hook({"conversationId": DESK, "invocationNum": 1}))
        self.assertEqual(self._explicit(SUBAGENT), 0)
        self.assertNotIn("--desk-thread", self._hook({"conversationId": DESK, "invocationNum": 0}))


if __name__ == "__main__":
    unittest.main()
