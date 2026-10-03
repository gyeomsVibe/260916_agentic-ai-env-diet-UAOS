"""U134-A: a real turn start proves capacity, so it clears a stale LIMITED/ABSENT lease of the same tool.

Receipt (2026-10-03, P1): a hand-written `coord presence --tool codex --state LIMITED --lease` from 2026-09-30 stayed
live for 3 days; presence dropped every Codex SessionStart/UserPromptSubmit heartbeat (U47-A1b), so the desk kept
saying codex=LIMITED while Codex answered in the app, and a Claude handoff never reached it.
A SessionStart or UserPromptSubmit heartbeat (`turn_start=True`) now replaces the lease and logs
LEASE_CLEARED_BY_TURN; a PostToolUse heartbeat is mid-turn and still cannot. Fixed acceptance written by the judge.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence


class LeaseClearedByTurnTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        presence.mark(self.project, "codex", "LIMITED", ttl_s=3 * 86400, lease=True)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _events(self):
        path = self.project / ".coord" / "presence" / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def test_a_turn_start_heartbeat_clears_a_stale_limited_lease(self):
        presence.mark(self.project, "codex", "ACTIVE", session="s1", turn_start=True)
        self.assertEqual("ACTIVE", presence.read(self.project, "codex")["state"])
        events = self._events()
        self.assertEqual(["LEASE_CLEARED_BY_TURN"], [e["kind"] for e in events])
        self.assertEqual(("codex", "LIMITED"), (events[0]["tool"], events[0]["cleared_state"]))

    def test_a_mid_turn_heartbeat_leaves_the_lease(self):
        presence.mark(self.project, "codex", "ACTIVE", session="s1")  # PostToolUse: turn_start defaults to False
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])
        self.assertEqual([], self._events())

    def test_a_turn_start_never_clears_another_tools_lease(self):
        presence.mark(self.project, "claude", "ACTIVE", session="s2", turn_start=True)
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])

    def test_an_absent_lease_is_cleared_too_and_a_limited_turn_clears_nothing(self):
        presence.mark(self.project, "claude", "ABSENT", ttl_s=3600, lease=True)
        presence.mark(self.project, "claude", "LIMITED", session="s3", turn_start=True)
        self.assertEqual("ABSENT", presence.read(self.project, "claude")["state"])  # only ACTIVE proves capacity
        presence.mark(self.project, "claude", "ACTIVE", session="s3", turn_start=True)
        self.assertEqual("ACTIVE", presence.read(self.project, "claude")["state"])

    def test_the_hook_payload_names_a_turn_start(self):
        for event, expected in (("SessionStart", True), ("UserPromptSubmit", True), ("PostToolUse", False),
                                ("Stop", False), (None, False)):
            payload = json.dumps({"session_id": "s", "hook_event_name": event} if event else {"session_id": "s"})
            self.assertEqual(expected, presence.hook_turn_start(payload), event)
        self.assertFalse(presence.hook_turn_start("not json"))
        self.assertFalse(presence.hook_turn_start(""))

    def test_the_cli_hook_clears_the_lease_on_session_start_only(self):
        from v7_harness import cli

        def run(event):
            stdin = io.StringIO(json.dumps({"session_id": "s9", "hook_event_name": event, "cwd": str(self.project)}))
            argv = ["coord", "presence", "--tool", "codex", "--state", "ACTIVE", "--from-hook", "--say", "none",
                    "--project", str(self.project)]
            if event == "PostToolUse":
                argv.append("--post-tool")
            with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", new_callable=io.StringIO), \
                    mock.patch.dict(os.environ, {"UAOS_WORKER": ""}):
                args = cli.build_parser().parse_args(argv)
                self.assertEqual(0, args.func(args))

        run("PostToolUse")
        self.assertEqual("LIMITED", presence.read(self.project, "codex")["state"])
        run("SessionStart")
        self.assertEqual("ACTIVE", presence.read(self.project, "codex")["state"])


if __name__ == "__main__":
    unittest.main()
