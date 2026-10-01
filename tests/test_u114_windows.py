"""U114: one process (card) gets one dedicated, named window in each tool, the same way for all three tools.

The user asked (2026-10-01) for Codex's habit, a lone user thread plus one "[U##] ..." thread per process, in all three
tools. Smallest proofs on this PC (0 or 1 tiny paid call):
- Codex 0.159.3: `codex app-server` thread/start + thread/name/set made "[U114] ..." in ~/.codex/session_index.jsonl in
  5 s with no model call; the rollout (and so the sidebar row) appears only after the first turn.
- Claude Code 2.1.286: `claude --bg --name "[U114] ..."` started a named background session in 3 s (`claude agents`).
- Antigravity: `agy -p --output-format json` returns conversation_id; `--conversation <id>` continues it.
A window is a record `.coord/windows/<card>.json` {card, title, tools: {tool: {id, opened_at}}}; a card opened twice in
the same tool reuses its window. A LIMITED or ABSENT tool gets no window (U113: nothing waits in a limited thread).
Fixed acceptance written by the judge (claude) first; every runner is faked, so no test starts a paid session.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord import windows


class _Done:
    def __init__(self, stdout=""):
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


class _Runner:
    def __init__(self, stdout=""):
        self.calls, self.stdout = [], stdout

    def __call__(self, command, **kw):
        self.calls.append((list(command), kw.get("cwd")))
        return _Done(self.stdout)


class _FakeCodex:
    """Stands in for the app-server JSON-RPC exchange: records each (method, params) and answers like 0.159.3."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, params):
        self.calls.append((method, params))
        return {"thread": {"id": "thread-1"}} if method == "thread/start" else {}


class WindowsTest(unittest.TestCase):
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

    def test_title_is_the_card_in_brackets(self):
        self.assertEqual("[U114] 창 분리", windows.window_title("U114", "창 분리"))

    def test_claude_window_is_a_named_background_session_with_the_id_it_prints(self):
        # Live probe 2026-10-01: `--bg` ignores `--session-id` ("--bg manages the session id"), so the id comes from
        # the banner it prints; `claude attach|logs|stop <id>` take that id.
        runner = _Runner(stdout="backgrounded · 41fe6b35 · [U114] 창 분리\n  claude agents             list sessions\n")
        opened = windows.open_window(self.project, "U114", "claude", "창 분리", "read the manual", runner=runner)
        command, cwd = runner.calls[0]
        self.assertIn("--bg", command)
        self.assertNotIn("--session-id", command)
        self.assertEqual("[U114] 창 분리", command[command.index("--name") + 1])
        self.assertEqual("41fe6b35", opened["id"])
        self.assertEqual("read the manual", command[-1])
        self.assertEqual(str(self.project), str(cwd))

    def test_antigravity_window_keeps_the_conversation_id_it_prints(self):
        runner = _Runner(stdout=json.dumps({"conversation_id": "conv-9", "response": "ok"}))
        opened = windows.open_window(self.project, "U114", "antigravity", "창 분리", "read the manual", runner=runner)
        command, _ = runner.calls[0]
        self.assertIn("-p", command)
        self.assertEqual("json", command[command.index("--output-format") + 1])
        self.assertEqual("conv-9", opened["id"])

    def test_codex_window_is_an_app_server_thread_named_after_its_first_turn(self):
        presence.mark(self.project, "codex", "ACTIVE")
        rpc = _FakeCodex()
        opened = windows.open_window(self.project, "U114", "codex", "창 분리", "read the manual", rpc=rpc)
        methods = [method for method, _ in rpc.calls]
        self.assertEqual(["thread/start", "turn/start", "thread/name/set"], methods)  # name after the first turn
        self.assertEqual(str(self.project), rpc.calls[0][1]["cwd"])
        self.assertEqual({"threadId": "thread-1", "name": "[U114] 창 분리"}, rpc.calls[2][1])
        self.assertEqual("thread-1", opened["id"])

    def test_a_claude_start_without_an_id_records_nothing(self):
        with self.assertRaises(RuntimeError):
            windows.open_window(self.project, "U114", "claude", "x", "go", runner=_Runner(stdout="error: not logged in"))
        self.assertIsNone(windows.window_for(self.project, "U114", "claude"))

    def test_the_record_is_shared_and_a_second_open_reuses_the_window(self):
        runner = _Runner(stdout="backgrounded · 0a1b2c3d · [U114] 창 분리\n")
        first = windows.open_window(self.project, "U114", "claude", "창 분리", "go", runner=runner)
        second = windows.open_window(self.project, "U114", "claude", "창 분리", "go again", runner=runner)
        self.assertEqual(1, len(runner.calls))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["id"], windows.window_for(self.project, "U114", "claude"))
        record = json.loads((self.project / ".coord" / "windows" / "U114.json").read_text(encoding="utf-8"))
        self.assertEqual("[U114] 창 분리", record["title"])
        self.assertIn("claude", record["tools"])
        self.assertIsNone(windows.window_for(self.project, "U114", "codex"))

    def test_a_limited_or_absent_tool_gets_no_window(self):
        for state in ("LIMITED", "ABSENT"):
            presence.mark(self.project, "codex", state)
            rpc = _FakeCodex()
            opened = windows.open_window(self.project, "U115", "codex", "x", "go", rpc=rpc)
            self.assertEqual([], rpc.calls, state)
            self.assertEqual(state, opened["refused"], state)
            self.assertIsNone(windows.window_for(self.project, "U115", "codex"), state)

    def test_one_cli_command_opens_a_window_in_any_tool(self):
        from v7_harness import cli
        manual = self.project / "manual.md"
        manual.write_text("U114 manual body", encoding="utf-8")
        seen = {}

        def fake_open(project, card, tool, title, prompt, **_kw):
            seen.update(project=Path(project), card=card, tool=tool, title=title, prompt=prompt)
            return {"id": "w1", "reused": False}

        with mock.patch("v7_harness.coord.windows.open_window", side_effect=fake_open), \
                mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
            args = cli.build_parser().parse_args(["coord", "window", "--project", str(self.project), "--card", "U114",
                                                  "--tool", "antigravity", "--title", "창 분리",
                                                  "--prompt-file", str(manual)])
            self.assertEqual(0, args.func(args))
        self.assertEqual({"project": self.project, "card": "U114", "tool": "antigravity", "title": "창 분리",
                          "prompt": "U114 manual body"}, seen)  # the manual's content, not its path, is the prompt
        self.assertEqual("w1", json.loads(out.getvalue())["id"])

    def test_card_ids_cannot_escape_the_windows_folder(self):
        for bad in ("../x", "U1/2", "", "U114 x"):
            with self.assertRaises(ValueError, msg=bad):
                windows.open_window(self.project, bad, "claude", "x", "go", runner=_Runner())


if __name__ == "__main__":
    unittest.main()
