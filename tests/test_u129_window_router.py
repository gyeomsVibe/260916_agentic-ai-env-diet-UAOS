"""U129 re-scope (2026-10-02, 윤겸스 via the user window): every card-window route is clickless.

A task chip (spawn_task) needs a user click, so it is no route. The desktop app gives the user window no clickless
"create session" tool, but `send_message` into an existing visible session needs no click. Route order:
1. Codex app-server thread (visible in the Codex app) while Codex is ACTIVE;
2. an idle visible Claude desktop session that the conductor feeds by send_message, one card per session at a time;
3. Antigravity headless (`agy -p`), its result relayed.
No route or refusal may hand the user a click or command; only the Safety human list (merge, push, spend) may.
Fixed acceptance written by the judge (claude) first; no test starts a process.
"""

import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord import windows

S1 = "11111111-2222-3333-4444-555555555555"
S2 = "66666666-7777-8888-9999-aaaaaaaaaaaa"
# Words that hand the user a step: a click, a chip, a command to run, or a 남은 일 line.
USER_STEP_RE = re.compile(r"click|spawn_task|chip|run this|you run|user must|클릭|실행하세요|남은 일|사용자가", re.I)


def _no_runner(*_a, **_kw):
    raise AssertionError("routing must not start a process")


class WindowRouterTest(unittest.TestCase):
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

    def test_an_active_codex_takes_the_card_first(self):
        presence.mark(self.project, "codex", "ACTIVE")
        self.assertEqual("codex", windows.route_window(self.project, "U129", session_id=S1)["route"])

    def test_without_codex_an_idle_visible_claude_session_takes_it(self):
        presence.mark(self.project, "codex", "LIMITED")
        route = windows.route_window(self.project, "U129", session_id=S1.upper())
        self.assertEqual(("claude", S1), (route["route"], route["session_id"]))
        self.assertIn("send_message", route["step"])

    def test_without_codex_or_an_idle_session_antigravity_runs_headless(self):
        presence.mark(self.project, "codex", "LIMITED")
        route = windows.route_window(self.project, "U129")
        self.assertEqual("antigravity", route["route"])
        self.assertIn("agy -p", route["step"])

    def test_a_session_holding_another_card_is_busy_and_skipped(self):
        presence.mark(self.project, "codex", "LIMITED")
        windows.open_window(self.project, "U130", "claude", "x", "", runner=_no_runner, session_id=S1)
        self.assertEqual("U130", windows.session_busy(self.project, S1, "U129"))
        route = windows.route_window(self.project, "U129", session_id=S1)
        self.assertEqual(("antigravity", "U130"), (route["route"], route["busy"]))
        refused = windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner, session_id=S1)
        self.assertEqual(("SESSION_BUSY", "U130"), (refused["refused"], refused["held_by"]))
        self.assertIsNone(windows.window_for(self.project, "U129", "claude"))
        # Another idle session is fine, and a card may re-route to the session it already holds.
        self.assertEqual("claude", windows.route_window(self.project, "U129", session_id=S2)["route"])
        self.assertIsNone(windows.session_busy(self.project, S1, "U130"))

    def test_a_released_card_frees_its_session(self):
        presence.mark(self.project, "codex", "LIMITED")
        windows.open_window(self.project, "U130", "claude", "x", "", runner=_no_runner, session_id=S1)
        released = windows.release_window(self.project, "U130", "claude", now=9.0)
        self.assertEqual({"released": True, "card": "U130", "tool": "claude"}, released)
        record = json.loads((self.project / ".coord" / "windows" / "U130.json").read_text(encoding="utf-8"))
        self.assertEqual(9.0, record["tools"]["claude"]["released_at"])
        self.assertIsNone(windows.session_busy(self.project, S1, "U129"))
        opened = windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner, session_id=S1)
        self.assertEqual(S1, opened["id"])
        self.assertEqual({"released": False, "card": "U131", "tool": "claude"},
                         windows.release_window(self.project, "U131", "claude"))

    def test_no_route_or_refusal_hands_the_user_a_step(self):
        outputs = []
        for codex in ("ACTIVE", "LIMITED"):
            presence.mark(self.project, "codex", codex)
            outputs += [windows.route_window(self.project, "U129"),
                        windows.route_window(self.project, "U129", session_id=S2)]
        presence.mark(self.project, "codex", "LIMITED")
        windows.open_window(self.project, "U130", "claude", "x", "", runner=_no_runner, session_id=S1)
        outputs += [windows.route_window(self.project, "U129", session_id=S1),
                    windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner),
                    windows.open_window(self.project, "U129", "claude", "x", "", runner=_no_runner, session_id=S1)]
        for output in outputs:
            text = json.dumps(output, ensure_ascii=False)
            self.assertIsNone(USER_STEP_RE.search(text), text)
            self.assertTrue(output.get("step") or output.get("message"), text)

    def _cli(self, *extra, prompt=True):
        from v7_harness import cli
        manual = self.project / "manual.md"
        manual.write_text("U129 manual body", encoding="utf-8")
        argv = ["coord", "window", "--project", str(self.project), "--card", "U129", "--title", "x", *extra]
        if prompt:
            argv += ["--prompt-file", str(manual)]
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            args = cli.build_parser().parse_args(argv)
            code = args.func(args)
        return code, json.loads(out.getvalue())

    def test_the_cli_auto_tool_opens_the_routed_window(self):
        presence.mark(self.project, "codex", "LIMITED")
        code, result = self._cli("--tool", "auto", "--session-id", S1)
        self.assertEqual((0, "claude", S1), (code, result["route"], result["id"]))
        seen = {}

        def fake_open(project, card, tool, title, prompt, **kw):
            seen.update(tool=tool, prompt=prompt, kw=kw)
            return {"id": "conv-1", "reused": False}

        with mock.patch("v7_harness.coord.windows.open_window", side_effect=fake_open):
            code, result = self._cli("--tool", "auto")
        self.assertEqual((0, "antigravity", "conv-1"), (code, result["route"], result["id"]))
        self.assertEqual({"tool": "antigravity", "prompt": "U129 manual body", "kw": {}}, seen)

    def test_the_cli_release_frees_the_card_window(self):
        presence.mark(self.project, "codex", "LIMITED")
        self._cli("--tool", "claude", "--session-id", S1, prompt=False)
        code, result = self._cli("--tool", "claude", "--release", prompt=False)
        self.assertEqual((0, True), (code, result["released"]))
        code, result = self._cli("--tool", "claude", "--release", prompt=False)
        self.assertEqual(0, code)  # releasing twice is harmless


if __name__ == "__main__":
    unittest.main()
