"""U58 frozen acceptance (written by Claude): one session ending does not mark the whole tool absent.

Seen 2026-09-28: `coord deliver` started a cold `claude -p`; its SessionEnd hook wrote claude ABSENT for 24 h and
`coord route` answered BLOCKED_NO_ACTIVE_AUTHORITY while the acting conductor's own session was still open.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.cli import main
from v7_harness.coord.hook_context import hook_session
from v7_harness.coord.presence import mark, read

T0 = 1_000_000.0


class SessionPresenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_one_session_ending_leaves_the_other_at_the_desk(self):
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0, session="A")
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0 + 10, session="B")
        mark(self.project, "claude", "ABSENT", ttl_s=86400, now=T0 + 20, session="B")
        desk = read(self.project, "claude", now=T0 + 30)
        self.assertEqual("ACTIVE", desk["state"])
        self.assertEqual(T0 + 3600, desk["expires_at"])

    def test_last_session_ending_marks_absent(self):
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0, session="A")
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0 + 10, session="B")
        mark(self.project, "claude", "ABSENT", ttl_s=86400, now=T0 + 20, session="B")
        mark(self.project, "claude", "ABSENT", ttl_s=86400, now=T0 + 30, session="A")
        self.assertEqual("ABSENT", read(self.project, "claude", now=T0 + 40)["state"])

    def test_an_expired_session_does_not_keep_the_desk(self):
        mark(self.project, "claude", "ACTIVE", ttl_s=100, now=T0, session="A")
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0 + 200, session="B")
        mark(self.project, "claude", "ABSENT", ttl_s=86400, now=T0 + 300, session="B")
        self.assertEqual("ABSENT", read(self.project, "claude", now=T0 + 310)["state"])

    def test_a_session_heartbeat_extends_to_the_latest_live_session(self):
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0, session="A")
        mark(self.project, "claude", "ACTIVE", ttl_s=60, now=T0 + 10, session="B")
        self.assertEqual(T0 + 3600, read(self.project, "claude", now=T0 + 20)["expires_at"])

    def test_calls_without_a_session_still_replace_the_state(self):
        mark(self.project, "claude", "ACTIVE", ttl_s=3600, now=T0, session="A")
        mark(self.project, "claude", "ABSENT", ttl_s=86400, now=T0 + 10)
        self.assertEqual("ABSENT", read(self.project, "claude", now=T0 + 20)["state"])

    def test_a_live_lease_still_wins_over_session_heartbeats(self):
        mark(self.project, "codex", "LIMITED", ttl_s=7200, now=T0, lease=True)
        mark(self.project, "codex", "ACTIVE", ttl_s=3600, now=T0 + 10, session="A")
        self.assertEqual("LIMITED", read(self.project, "codex", now=T0 + 20)["state"])


class HookSessionTest(unittest.TestCase):
    def test_hook_session_reads_the_payload_id(self):
        self.assertEqual("abc", hook_session(json.dumps({"session_id": "abc", "cwd": "."})))
        for text in ("", "not json", "[]", json.dumps({"session_id": 5}), json.dumps({"session_id": "  "})):
            self.assertIsNone(hook_session(text))

    def test_hook_path_passes_the_session_to_the_desk(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".coord").mkdir()
            (Path(d) / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

            def hook(state, session):
                payload = json.dumps({"session_id": session, "cwd": d})
                with redirect_stdout(io.StringIO()), \
                        mock.patch("v7_harness.coord.hook_context.read_stdin", return_value=payload), \
                        mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "", "UAOS_WORKER": ""}):
                    return main(["coord", "presence", "--tool", "claude", "--state", state, "--from-hook",
                                 "--project", d, "--say", "none"])

            self.assertEqual(0, hook("ACTIVE", "main-session"))
            self.assertEqual(0, hook("ACTIVE", "cold-child"))
            self.assertEqual(0, hook("ABSENT", "cold-child"))
            self.assertEqual("ACTIVE", read(Path(d), "claude")["state"])
            self.assertEqual(0, hook("ABSENT", "main-session"))
            self.assertEqual("ABSENT", read(Path(d), "claude")["state"])


if __name__ == "__main__":
    unittest.main()
