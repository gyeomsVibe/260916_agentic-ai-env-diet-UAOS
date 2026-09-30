"""U105: a letter or P1 that lands while a tool is mid-turn reaches that tool at its next tool call, in all three tools.

Receipt (윤겸스, 2026-10-01): the user pasted status lines between tools by hand, because each tool heard of new letters
only when the user typed the next prompt (UserPromptSubmit, or Antigravity's first PreInvocation of a turn). A long
autonomous turn therefore ran blind to a new verdict or P1. Per-tool route (docs/65 §5-2):
- Claude Code: PostToolUse hook (every tool) prints JSON `hookSpecificOutput.additionalContext` - plain stdout on
  PostToolUse never reaches the model.
- Codex: PostToolUse hook (matcher Bash, the tool Codex hooks see) with the same JSON shape.
- Antigravity: its PreInvocation hook already runs on every model call; the desk delta is no longer limited to the
  turn's first call (invocationNum 0). The delta cursor keeps a repeat silent.
The mid-turn hooks pass no --state, so a tool call writes no presence file. Written by the judge (claude) before the
implementation; the worker must not edit it.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


class MidTurnHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inbox = self.root / ".coord" / "mailbox" / "inbox"
        self.inbox.mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _letter(self, name: str, actor: str, message: str) -> None:
        (self.inbox / f"{name}.json").write_text(json.dumps({"payload": {"actor": actor, "message": message}}),
                                                 encoding="utf-8")

    def _hook(self, argv_tail: list[str], payload: dict) -> str:
        from v7_harness.cli import main

        argv = ["coord", "presence", "--from-hook", "--project", str(self.root)] + argv_tail
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": "", "UAOS_WORKER": ""}), \
                mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=json.dumps(payload)):
            self.assertEqual(0, main(argv))
        return out.getvalue()

    def _post(self, tool: str, say: str, session: str = "c1") -> str:
        return self._hook(["--tool", tool, "--say", say, "--delta", "--post-tool"],
                          {"session_id": session, "hook_event_name": "PostToolUse"})

    def _context(self, text: str) -> str:
        data = json.loads(text)
        self.assertEqual("PostToolUse", data["hookSpecificOutput"]["hookEventName"])
        return data["hookSpecificOutput"]["additionalContext"]

    def test_claude_hears_a_new_letter_mid_turn_once(self) -> None:
        self._letter("relay_x1", "codex", "codex verdict U105")
        self.assertIn("codex verdict U105", self._context(self._post("claude", "p1")))
        self.assertEqual("", self._post("claude", "p1").strip())

    def test_claude_hears_a_p1_mid_turn(self) -> None:
        (self.inbox / "wake_0001.json").write_text(json.dumps({"payload": {"wake_reason": "failed gate U9"}}),
                                                   encoding="utf-8")
        self.assertIn("UAOS P1 waiting", self._context(self._post("claude", "p1")))

    def test_codex_hears_a_new_letter_mid_turn(self) -> None:
        self._letter("relay_c1", "claude", "claude bundle ready")
        self.assertIn("claude bundle ready", self._context(self._post("codex", "none", session="x1")))

    def test_nothing_new_prints_nothing(self) -> None:
        self.assertEqual("", self._post("claude", "p1").strip())

    def test_mid_turn_hook_writes_no_presence(self) -> None:
        self._letter("relay_x2", "codex", "codex note")
        self._post("claude", "p1")
        self.assertFalse((self.root / ".coord" / "presence" / "claude.json").exists())

    def test_antigravity_hears_a_letter_on_a_later_call_of_the_turn(self) -> None:
        tail = ["--tool", "antigravity", "--state", "ACTIVE", "--say", "agy", "--delta"]
        self._hook(tail, {"conversationId": "g1", "invocationNum": 0})
        self._letter("relay_x3", "codex", "codex verdict for agy")
        later = json.loads(self._hook(tail, {"conversationId": "g1", "invocationNum": 3}))
        self.assertIn("codex verdict for agy", later["injectSteps"][0]["ephemeralMessage"])
        again = json.loads(self._hook(tail, {"conversationId": "g1", "invocationNum": 4}))
        self.assertEqual({}, again)


class MidTurnInstallTests(unittest.TestCase):
    """The installer wires the mid-turn hook for Claude and Codex in their own formats (temporary HOME)."""

    def test_claude_and_codex_get_a_post_tool_hook(self) -> None:
        from tests.test_u37_install_everywhere import _home, _run

        with tempfile.TemporaryDirectory() as temp:
            home = _home(Path(temp))
            self.assertEqual(0, _run(home, "--apply")[0])
            claude = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
            codex = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
            self.assertEqual(0, _run(home, "--check")[0])
        claude_group = claude["PostToolUse"][-1]
        self.assertNotIn("matcher", claude_group)  # every Claude tool call
        claude_cmd = claude_group["hooks"][0]["command"]
        for part in ("--tool claude", "--say p1", "--delta", "--post-tool"):
            self.assertIn(part, claude_cmd)
        self.assertNotIn("--state", claude_cmd)
        codex_group = codex["PostToolUse"][-1]
        self.assertEqual("Bash", codex_group["matcher"])
        codex_cmd = codex_group["hooks"][0]["command"]
        for part in ("--tool codex", "--say none", "--delta", "--post-tool"):
            self.assertIn(part, codex_cmd)
        self.assertNotIn("--state", codex_cmd)


if __name__ == "__main__":
    unittest.main()
