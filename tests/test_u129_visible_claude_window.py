"""U129: a Claude card window is a session the user can see in the Claude desktop app, never a `claude --bg` job.

Receipt (2026-10-02): three `coord window --tool claude` jobs ran as `claude --bg` background sessions, which the
desktop app does not list (agent view and /bg are terminal-only, code.claude.com/docs/en/agent-view and claudeissues
75624; the desktop keeps its own session list and does not move a running background session,
code.claude.com/docs/en/desktop). One burned 36 calls (~3.3M cache-read tokens) unseen. So `coord window --tool claude`
launches nothing: it records the id of a visible desktop session the caller gives (`--session-id`, the Claude Code
session UUID, e.g. CLAUDE_CODE_SESSION_ID inside that session) and otherwise refuses, naming the visible path.
Fixed acceptance written by the judge (claude) first; no test starts a process.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord import windows

SESSION = "46b09584-c7ba-434e-8714-f4cce3058dbd"
ROOT = Path(__file__).resolve().parents[1]


def _no_runner(*_a, **_kw):
    raise AssertionError("a Claude card window must not start a process")


class VisibleClaudeWindowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_a_given_desktop_session_is_recorded_without_starting_anything(self):
        opened = windows.open_window(self.project, "U129", "claude", "보이는 창", "", runner=_no_runner,
                                     session_id=SESSION, now=5.0)
        self.assertEqual({"id": SESSION, "opened_at": 5.0, "reused": False}, opened)
        self.assertEqual(SESSION, windows.window_for(self.project, "U129", "claude"))
        record = json.loads((self.project / ".coord" / "windows" / "U129.json").read_text(encoding="utf-8"))
        self.assertEqual("[U129] 보이는 창", record["title"])

    def test_an_upper_case_id_is_stored_lower_case(self):
        opened = windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner,
                                     session_id=SESSION.upper())
        self.assertEqual(SESSION, opened["id"])

    def test_without_a_session_id_it_refuses_and_names_the_visible_path(self):
        opened = windows.open_window(self.project, "U129", "claude", "x", "read the manual", runner=_no_runner)
        self.assertEqual("NO_VISIBLE_SESSION", opened["refused"])
        self.assertEqual(("claude", "U129"), (opened["tool"], opened["card"]))
        self.assertIn("--session-id", opened["message"])
        self.assertIn("spawn_task", opened["message"])
        self.assertIsNone(windows.window_for(self.project, "U129", "claude"))
        self.assertFalse((self.project / ".coord" / "windows" / "U129.json").exists())

    def test_a_recorded_window_is_reused_without_a_session_id(self):
        windows.open_window(self.project, "U129", "claude", "x", "", session_id=SESSION)
        again = windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner)
        self.assertEqual({"id": SESSION, "reused": True}, {k: again[k] for k in ("id", "reused")})

    def test_a_malformed_session_id_is_rejected_and_records_nothing(self):
        # A banner prefix ("41fe6b35"), a path, or a desktop sidebar label is not a resumable session id.
        for bad in ("41fe6b35", "../x", "[U129] 보이는 창", SESSION + "0", ""):
            with self.assertRaises(ValueError, msg=bad):
                windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner, session_id=bad)
        self.assertIsNone(windows.window_for(self.project, "U129", "claude"))

    def test_a_session_id_is_for_claude_only(self):
        with self.assertRaises(ValueError):
            windows.open_window(self.project, "U129", "antigravity", "x", "go", runner=_no_runner, session_id=SESSION)

    def test_no_background_launch_is_left_in_the_window_module(self):
        source = (ROOT / "v7_harness" / "coord" / "windows.py").read_text(encoding="utf-8")
        self.assertNotIn('"--bg"', source)
        self.assertNotIn("'--bg'", source)

    def test_the_session_id_pattern_carries_its_reason(self):
        # Verification rule: an unexplained value is a defect; U129-L3 dropped these comment lines.
        source = (ROOT / "v7_harness" / "coord" / "windows.py").read_text(encoding="utf-8")
        above = source[:source.index("SESSION_ID_RE = ")].splitlines()[-2:]
        self.assertTrue(all(line.startswith("# ") for line in above), above)
        self.assertIn("CLAUDE_CODE_SESSION_ID", "\n".join(above))

    def _cli(self, *extra):
        from v7_harness import cli
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            args = cli.build_parser().parse_args(["coord", "window", "--project", str(self.project), "--card", "U129",
                                                  "--tool", "claude", "--title", "보이는 창", *extra])
            code = args.func(args)
        return code, json.loads(out.getvalue())

    def test_the_cli_records_a_session_id_without_a_prompt_file(self):
        code, result = self._cli("--session-id", SESSION)
        self.assertEqual(0, code)
        self.assertEqual(SESSION, result["id"])

    def test_the_cli_refuses_with_exit_2_when_no_session_id_is_given(self):
        code, result = self._cli()
        self.assertEqual(2, code)
        self.assertEqual("NO_VISIBLE_SESSION", result["refused"])

    def test_codex_and_antigravity_still_need_a_prompt_file(self):
        from v7_harness import cli
        for tool in ("codex", "antigravity"):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                    mock.patch("v7_harness.coord.windows.open_window", side_effect=AssertionError("opened")):
                args = cli.build_parser().parse_args(["coord", "window", "--project", str(self.project),
                                                      "--card", "U129", "--tool", tool, "--title", "x"])
                self.assertEqual(2, args.func(args), tool)
            self.assertIn("--prompt-file", json.loads(out.getvalue())["error"], tool)


if __name__ == "__main__":
    unittest.main()
