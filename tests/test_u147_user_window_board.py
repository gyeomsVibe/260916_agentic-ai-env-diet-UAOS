"""U147: a letter to Codex reaches the window 윤겸스 typed in, and the board shows which tool works right now.

Receipt (2026-10-04): relay_54d2ee83 and relay_cf68f9ce went to background Codex thread 01a1006f, the newest-written
rollout, not the user's window 01a102e7, so the user saw no reaction. Rules under test:
1. Without --thread, deliver picks the verified thread with the newest human-typed user turn; relays, sentinel data,
   AGENTS.md and <...> context blocks are not human turns.
2. With no human turn in any verified thread, the newest-written verified thread still wins (old behaviour).
3. The accepted receipt names the thread the letter went to.
4. The board marks a Codex thread WORKING while its last task_started has no later task_complete, marks the user
   window, and marks a Claude or Antigravity transcript written in the last 120 s as working.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import board, presence
from v7_harness.coord.deliver import deliver, last_human_input

USER = "0199aaaa-0000-7000-8000-000000000001"
BACKGROUND = "0199bbbb-0000-7000-8000-000000000002"


def _line(kind, payload, stamp):
    return json.dumps({"timestamp": stamp, "type": kind, "payload": payload}) + "\n"


def _user_turn(text, stamp):
    return _line("response_item", {"type": "message", "role": "user",
                                   "content": [{"type": "input_text", "text": text}]}, stamp)


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return mock.Mock(returncode=0, stdout="", stderr="")

    def threads(self):
        return [c[c.index("--thread") + 1] for c in self.calls if "--thread" in c]


class UserWindowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.project = base / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        (self.project / ".git" / "worktrees").mkdir(parents=True)
        self.sessions = base / "codex-sessions"
        self.claude = base / "claude-projects"
        self.agy = base / "agy-brain"
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions),
                                                 board.CLAUDE_PROJECTS_ENV: str(self.claude),
                                                 board.AGY_BRAIN_ENV: str(self.agy)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex")
        self._which.start()
        presence.mark(self.project, "codex", "ACTIVE")

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _rollout(self, thread, lines, age_s):
        day = self.sessions / "2026" / "10" / "04"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-04T02-00-00-{thread}.jsonl"
        meta = {"type": "session_meta", "payload": {"id": thread, "cwd": str(self.project.resolve())}}
        path.write_text(json.dumps(meta) + "\n" + "".join(lines), encoding="utf-8")
        moment = time.time() - age_s
        os.utime(path, (moment, moment))
        return path

    def _two_threads(self):
        # The user typed in USER at 17:54; BACKGROUND only got relays afterwards and was written last.
        self._rollout(USER, [_user_turn("# AGENTS.md instructions", "2026-10-03T17:54:55.000Z"),
                             _user_turn("윤겸스가 직접 쓴 지시", "2026-10-03T17:54:58.000Z")], age_s=600)
        self._rollout(BACKGROUND, [_user_turn("오래된 사용자 지시", "2026-10-03T12:36:35.000Z"),
                                   _user_turn("[UAOS relay id=relay_x] hello", "2026-10-03T18:23:00.000Z"),
                                   _user_turn("[DATA] from=sentinel", "2026-10-03T18:24:00.000Z"),
                                   _user_turn("<external_context>", "2026-10-03T18:25:00.000Z")], age_s=5)

    def test_last_human_input_skips_injected_turns(self):
        path = self._rollout(BACKGROUND, [_user_turn("사람 입력", "2026-10-03T12:00:00.000Z"),
                                          _user_turn("[UAOS relay id=r] x", "2026-10-03T13:00:00.000Z")], 1)
        self.assertEqual(last_human_input(path), "2026-10-03T12:00:00.000Z")

    def test_letter_goes_to_window_user_typed_in_last(self):
        self._two_threads()
        runner = _Runner()
        result = deliver(self.project, actor="claude", target="codex", message="ACTIONABLE_DELTA hi", runner=runner)
        self.assertEqual(result.reason, "DISPATCHED")
        self.assertEqual(runner.threads(), [USER])
        receipt = json.loads(Path(result.receipt).read_text(encoding="utf-8"))
        self.assertEqual(receipt["thread"], USER)

    def test_without_human_turns_newest_written_wins(self):
        self._rollout(USER, [_user_turn("[UAOS relay id=a] x", "2026-10-03T10:00:00.000Z")], age_s=600)
        self._rollout(BACKGROUND, [], age_s=5)
        runner = _Runner()
        deliver(self.project, actor="claude", target="codex", message="ACTIONABLE_DELTA hi", runner=runner)
        self.assertEqual(runner.threads(), [BACKGROUND])

    def test_board_shows_working_states_and_user_window(self):
        self._two_threads()
        running = _line("event_msg", {"type": "task_started"}, "2026-10-03T18:30:00.000Z")
        self._rollout(BACKGROUND, [_user_turn("오래된 사용자 지시", "2026-10-03T12:36:35.000Z"),
                                   _line("event_msg", {"type": "task_complete", "last_agent_message": "done"},
                                         "2026-10-03T18:29:00.000Z"), running], age_s=5)
        key = board._project_key(self.project)
        live = self.claude / f"D--x-{key}"
        live.mkdir(parents=True)
        (live / "s-live.jsonl").write_text("{}\n", encoding="utf-8")
        old = live / "s-old.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        os.utime(old, (time.time() - 600, time.time() - 600))
        agy = self.agy / "conv1" / ".system_generated" / "logs"
        agy.mkdir(parents=True)
        (agy / "transcript_full.jsonl").write_text("{}\n", encoding="utf-8")

        snap = board.snapshot(self.project)
        codex = {row["thread"]: row for row in snap["codex"]}
        self.assertTrue(codex[BACKGROUND]["working"])
        self.assertFalse(codex[USER]["working"])
        self.assertTrue(codex[USER]["user_window"])
        self.assertFalse(codex[BACKGROUND]["user_window"])
        claude = {row["session"]: row["working"] for row in snap["claude"]}
        self.assertEqual(claude, {"s-live": True, "s-old": False})
        self.assertTrue(snap["antigravity"][0]["working"])
        text = "\n".join(board.lines(snap))
        self.assertIn("사용자 창", text)
        page = board.write_html(self.project)
        self.assertIn("http-equiv='refresh'", page.read_text(encoding="utf-8"))

    def test_in_app_line_names_letters_and_other_tools_once_per_change(self):
        self._rollout(BACKGROUND, [_line("event_msg", {"type": "task_started"}, "2026-10-03T18:30:00.000Z")], 5)
        delta = "DESK DELTA for claude (2 items)\n- letter relay_abc: Codex verdict PASS\n- uncommitted M a.py"
        self.assertEqual(board.letters_in(delta), ["Codex verdict PASS"])
        line = board.status_line(self.project, "claude", board.letters_in(delta))
        self.assertIn("📬 새 편지 1통: Codex verdict PASS", line)
        self.assertIn("Codex 작업 중", line)
        self.assertIn("Antigravity 대기", line)
        self.assertNotIn("Claude", line)  # the app's own tool is not repeated
        self.assertTrue(board.line_is_new(self.project, "claude", line))  # a letter speaks even on the first look
        same = board.status_line(self.project, "claude", [])
        self.assertFalse(board.line_is_new(self.project, "claude", same))  # letter handed over, states unchanged
        quiet = board.status_line(self.project, "codex", [])
        self.assertFalse(board.line_is_new(self.project, "codex", quiet))  # first look only records
        self.assertTrue(board.line_is_new(self.project, "codex", quiet.replace("대기", "작업 중")))

    def test_hook_shows_line_to_user_as_system_message(self):
        import contextlib
        import io

        from v7_harness.cli import main as cli_main

        self._rollout(BACKGROUND, [_line("event_msg", {"type": "task_started"}, "2026-10-03T18:30:00.000Z")], 5)
        event = json.dumps({"hook_event_name": "PostToolUse", "cwd": str(self.project), "session_id": "s1"})
        argv = ["coord", "presence", "--tool", "claude", "--from-hook", "--say", "p1", "--delta", "--post-tool",
                "--project", str(self.project)]

        def run():
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(event)), contextlib.redirect_stdout(out):
                cli_main(argv)
            return out.getvalue().strip()

        self.assertNotIn("systemMessage", run())  # the first look records the states silently
        self._rollout(BACKGROUND, [_line("event_msg", {"type": "task_started"}, "2026-10-03T18:30:00.000Z"),
                                   _line("event_msg", {"type": "task_complete"}, "2026-10-03T18:31:00.000Z")], 5)
        changed = json.loads(run())
        self.assertIn("Codex 대기", changed["systemMessage"])
        self.assertNotIn("systemMessage", run())  # unchanged states stay silent


if __name__ == "__main__":
    unittest.main()
