"""U95-A: Antigravity can be addressed by a UAOS letter, and its presence hook tells it once per change.

Seen 2026-09-30: the Antigravity presence hook printed only {} and `coord deliver --target` accepted only codex and
claude, so Antigravity never learned from UAOS what waited for it; every work order reached it through the user.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.coord.deliver import deliver
from v7_harness.coord.hook_context import agy_letters, agy_line
from v7_harness.coord.mailbox import Mailbox

DESK = {"codex": {"state": "ABSENT"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}


def _event(conversation: str, invocation: int = 0) -> str:
    return json.dumps({"conversationId": conversation, "invocationNum": invocation})


class AntigravityBriefingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _order(self, text: str = "work order: read .coord/tasks/U95-R-manual.md") -> str:
        runner = mock.Mock(side_effect=AssertionError("antigravity has no CLI to dispatch to"))
        result = deliver(self.project, message=text, actor="claude", target="antigravity", runner=runner)
        self.assertEqual(("antigravity", "PUBLISHED"), (result.target, result.reason))
        return result.message_id

    def test_deliver_publishes_a_letter_addressed_to_antigravity_without_dispatch(self) -> None:
        message_id = self._order()
        self.assertEqual([message_id], agy_letters(self.project))

    def test_cli_accepts_antigravity_as_a_deliver_target(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["coord", "deliver", "--project", str(self.project), "--actor", "claude",
                         "--target", "antigravity", "--message", "work order: U95-R"])
        self.assertEqual(0, code)
        self.assertEqual("PUBLISHED", json.loads(out.getvalue())["reason"])

    def test_line_names_the_letter_once_per_conversation_and_again_when_letters_change(self) -> None:
        first_id = self._order()
        first = agy_line(self.project, DESK, _event("c1"))
        self.assertIn(first_id, first)
        self.assertIn("never judges its own work", first)
        self.assertEqual("", agy_line(self.project, DESK, _event("c1")))
        self.assertEqual("", agy_line(self.project, DESK, _event("c1", invocation=3)))
        second_id = self._order("work order: read .coord/tasks/U95-X-manual.md")
        again = agy_line(self.project, DESK, _event("c1"))
        self.assertIn(second_id, again)
        self.assertIn("2 letter(s)", again)
        self.assertIn(first_id, agy_line(self.project, DESK, _event("c2")))

    def test_letters_for_other_tools_are_not_named(self) -> None:
        (self.project / ".coord" / "mailbox").mkdir(exist_ok=True)
        Mailbox(self.project / ".coord" / "mailbox").publish(
            "relay_for_claude", {"kind": "HANDOFF", "actor": "codex", "message": "x", "requested_target": "claude"})
        self.assertEqual([], agy_letters(self.project))
        self.assertIn("No letter waits for antigravity", agy_line(self.project, DESK, _event("c1")))

    def test_presence_hook_prints_inject_steps_then_empty_json(self) -> None:
        self._order()
        payload = json.dumps({"conversationId": "c9", "invocationNum": 0, "workspacePaths": [str(self.project)]})

        def run() -> str:
            out = io.StringIO()
            # CLAUDE_PROJECT_DIR is emptied so a run inside a Claude Code session never finds the real desk.
            with redirect_stdout(out), mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": ""}), \
                    mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=payload):
                self.assertEqual(0, main(["coord", "presence", "--tool", "antigravity", "--state", "ACTIVE",
                                          "--from-hook", "--project", str(self.project), "--say", "agy"]))
            return out.getvalue()

        first = json.loads(run())
        self.assertIn("letter(s) for antigravity", first["injectSteps"][0]["ephemeralMessage"])
        self.assertEqual({}, json.loads(run()))


if __name__ == "__main__":
    unittest.main()
