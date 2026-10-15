"""U201: when a tool's turn ends while work waits or has stopped, the user sees why, in one Korean line.

Receipt (2026-10-16): Antigravity letters sat in the cap backlog from 00:00 to 00:40 and the Claude session showed
nothing, so 윤겸스 could not tell why everything had stopped. Stage 0: Claude Code and Codex Stop hooks show
`systemMessage` to the user (https://code.claude.com/docs/en/hooks, https://learn.chatgpt.com/docs/hooks.md);
Antigravity's Stop hook documents only `decision`/`reason` (https://antigravity.google/docs/hooks), so its result
is left as it is."""
import inspect
import json
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness import cli
from v7_harness.coord import wait_reason

NOW = 1792080000.0  # 2026-10-16 01:00 KST


class WaitReason(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "presence").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def park(self, count: int) -> None:
        folder = self.project / ".coord" / "mailbox" / "delivery" / "agy_backlog"
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (folder / f"relay_{index:032x}.json").write_text("{}", encoding="utf-8")
        (folder / "relay_old.failed").write_text("{}", encoding="utf-8")
        (folder / "relay_0.lock").write_text("", encoding="utf-8")

    def presence(self, tool: str, state: str, expires_at: float) -> None:
        (self.project / ".coord" / "presence" / f"{tool}.json").write_text(json.dumps(
            {"tool": tool, "state": state, "observed_at": "2026-10-15T15:00:00+00:00", "expires_at": expires_at}),
            encoding="utf-8")

    def gate_log(self, tool: str, card: str, at: float) -> None:
        log = self.project / ".coord" / "log" / "stop_gate.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "BLOCKED", "tool": tool, "card": card, "blocks": 1, "at": at}) + "\n")

    def test_nothing_waits_nothing_is_said(self):
        self.assertEqual([], wait_reason.reasons(self.project, "claude", now=NOW))
        self.assertIsNone(wait_reason.stop_output(None, self.project, "claude", now=NOW))

    def test_parked_antigravity_letters_are_named_with_the_cap(self):
        self.park(2)
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("Antigravity 답장 2건", lines[0])
        self.assertIn("한도", lines[0])

    def test_a_limited_tool_is_named_with_its_return_time(self):
        self.presence("codex", "LIMITED", NOW + 1800)  # 01:30 KST
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("codex", lines[0])
        self.assertIn("01:30", lines[0])

    def test_own_presence_and_active_tools_are_not_reasons(self):
        self.presence("claude", "LIMITED", NOW + 1800)
        self.presence("antigravity", "ACTIVE", NOW + 1800)
        self.assertEqual([], wait_reason.reasons(self.project, "claude", now=NOW))

    def test_a_recent_gate_stop_is_named_and_an_old_one_is_not(self):
        self.gate_log("claude", "U300", NOW - 120)
        self.gate_log("claude", "U299", NOW - 7200)
        self.gate_log("codex", "U298", NOW - 60)
        lines = wait_reason.reasons(self.project, "claude", now=NOW)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("U300", lines[0])

    def test_claude_and_codex_get_a_system_message_and_keep_the_decision(self):
        self.park(1)
        for tool in ("claude", "codex"):
            alone = wait_reason.stop_output(None, self.project, tool, now=NOW)
            self.assertTrue(alone["systemMessage"].startswith("⏸"), alone)
            self.assertNotIn("decision", alone)
            held = wait_reason.stop_output({"decision": "block", "reason": "NEXT U1"}, self.project, tool, now=NOW)
            self.assertEqual("block", held["decision"])
            self.assertEqual("NEXT U1", held["reason"])
            self.assertIn("Antigravity 답장 1건", held["systemMessage"])

    def test_antigravity_result_is_left_as_it_is(self):
        self.park(1)
        self.assertIsNone(wait_reason.stop_output(None, self.project, "antigravity", now=NOW))
        held = {"decision": "continue", "reason": "NEXT U1"}
        self.assertEqual(held, wait_reason.stop_output(dict(held), self.project, "antigravity", now=NOW))

    def test_the_stop_hook_uses_it(self):
        source = inspect.getsource(cli.cmd_coord_stop_gate)
        self.assertIn("stop_output(", source)
        # A cp949 Windows console cannot print "⏸"; the pilot raised UnicodeEncodeError, which the hook's fail-open
        # handler would swallow, so the hook prints ASCII-escaped JSON.
        self.assertNotIn("ensure_ascii=False", source)

    def test_default_now_is_the_clock(self):
        self.presence("codex", "LIMITED", time.time() + 600)
        self.assertEqual(1, len(wait_reason.reasons(self.project, "claude")))


if __name__ == "__main__":
    unittest.main()
