"""U147-R: Codex review counterexamples (relay_6dfa9184), kept apart from the frozen U147 test.

1. Twelve or more relay-only rollouts written after the user's window must not push it out of routing: the old code
   kept only the newest 12 rollouts before choosing the human window.
2. The board lists the user window even when more than CODEX_SCAN verified threads are newer.
3. Claude and Antigravity states come from write times: they read "최근 기록", Antigravity says it covers every
   project, and only Codex says "작업 중".
"""

import os
import time
import unittest
from unittest import mock

import json

from v7_harness.coord import board
from v7_harness.coord import deliver as deliver_module
from v7_harness.coord.deliver import _newest_verified_thread, deliver

from tests.test_u147_user_window_board import BACKGROUND, USER, UserWindowTest, _Runner, _line, _user_turn


class RouteCounterexampleTest(UserWindowTest):
    def _relay_only(self, count):
        for index in range(count):
            thread = f"0199cccc-0000-7000-8000-{index:012d}"
            self._rollout(thread, [_user_turn(f"[UAOS relay id=r{index}] x", "2026-10-03T19:00:00.000Z")],
                          age_s=4 - index * 0.01)

    def test_newer_relay_only_threads_do_not_starve_the_user_window(self):
        self._two_threads()
        self._relay_only(15)
        self.assertEqual(_newest_verified_thread(self.project, self.sessions), USER)
        runner = _Runner()
        deliver(self.project, actor="claude", target="codex", message="ACTIONABLE_DELTA hi", runner=runner)
        self.assertEqual(runner.threads(), [USER])

    def test_board_lists_user_window_beyond_scan(self):
        self._two_threads()
        self._relay_only(board.CODEX_SCAN + 2)
        rows = {row["thread"]: row for row in board.snapshot(self.project)["codex"]}
        self.assertTrue(rows[USER]["user_window"])

    def test_write_time_states_are_labelled_recent_and_global(self):
        self._rollout(USER, [_line("event_msg", {"type": "task_started"}, "2026-10-03T18:30:00.000Z")], 5)
        agy = self.agy / "conv1" / ".system_generated" / "logs"
        agy.mkdir(parents=True)
        (agy / "transcript_full.jsonl").write_text("{}\n", encoding="utf-8")
        live = self.claude / f"D--x-{board._project_key(self.project)}"
        live.mkdir(parents=True)
        (live / "s.jsonl").write_text("{}\n", encoding="utf-8")
        line = board.status_line(self.project, "codex", [])
        self.assertIn("Claude 최근 기록", line)
        self.assertIn("Antigravity 최근 기록(전체 프로젝트)", line)
        self.assertNotIn("Claude 작업 중", line)
        self.assertIn("Codex 작업 중", board.status_line(self.project, "claude", []))
        text = "\n".join(board.lines(board.snapshot(self.project)))
        self.assertIn("[Antigravity 전체 프로젝트]", text)

    def test_headless_agy_cli_conversations_count(self):
        # Antigravity review of U147-A4: pilot reviews and audits run the agy CLI, whose transcripts live in
        # ~/.gemini/antigravity-cli/brain, beside the desktop app's ~/.gemini/antigravity/brain.
        cli = self.agy.parent / "antigravity-cli" / "brain"
        logs = cli / "conv2" / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        (logs / "transcript_full.jsonl").write_text("{}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {board.AGY_BRAIN_ENV: os.pathsep.join([str(self.agy), str(cli)])}):
            rows = board.agy_conversations(time.time())
            self.assertEqual([(row["conversation"], row["kind"]) for row in rows], [("conv2", "CLI")])
            self.assertIn("Antigravity 최근 기록", board.status_line(self.project, "claude", []))
        with mock.patch.dict(os.environ, {board.AGY_BRAIN_ENV: ""}), \
                mock.patch("v7_harness.coord.board.Path.home", return_value=self.agy.parent.parent):
            self.assertEqual([str(root) for root in board._agy_roots()],
                             [str(self.agy.parent.parent / ".gemini" / "antigravity" / "brain"),
                              str(self.agy.parent.parent / ".gemini" / "antigravity-cli" / "brain")])


class DesignatedUserDeskTest(UserWindowTest):
    """U147-D (Codex relay_ef4ac44f): a designated user desk routes; the guess never truncates; stale fails closed."""

    def _relay_only(self, count):
        RouteCounterexampleTest._relay_only(self, count)

    def _send(self, runner=None):
        runner = runner or _Runner()
        result = deliver(self.project, actor="claude", target="codex", message="ACTIONABLE_DELTA hi", runner=runner)
        return result, runner

    def test_cap_overflow_fails_closed_without_a_desk_and_routes_with_one(self):
        self._two_threads()
        self._relay_only(deliver_module.ROUTE_SCAN_MAX)  # Codex's counterexample: 500 newer relay-only rollouts
        result, runner = self._send()
        self.assertEqual(result.reason, "NO_VERIFIED_THREAD")
        self.assertEqual(runner.threads(), [])  # never a guessed relay window
        self.assertTrue(deliver_module.register_user_desk(self.project, "codex", USER, source="test"))
        result, runner = self._send()
        self.assertEqual(runner.threads(), [USER])

    def test_designated_desk_beats_a_newer_human_turn_elsewhere(self):
        self._two_threads()
        deliver_module.register_user_desk(self.project, "codex", BACKGROUND, source="test")
        _result, runner = self._send()
        self.assertEqual(runner.threads(), [BACKGROUND])

    def test_stale_desk_fails_closed(self):
        self._two_threads()
        gone = "0199dddd-0000-7000-8000-000000000009"
        deliver_module.register_user_desk(self.project, "codex", gone, source="test")
        result, runner = self._send()
        self.assertEqual(result.reason, "USER_DESK_STALE")
        self.assertEqual(runner.threads(), [])
        other = self.project.parent / "other"
        other.mkdir()
        self._rollout(gone, [], age_s=1)
        meta_path = next(self.sessions.glob(f"*/*/*/rollout-*-{gone}.jsonl"))
        meta_path.write_text(json.dumps({"type": "session_meta", "payload": {"id": gone, "cwd": str(other)}}) + "\n",
                             encoding="utf-8")
        result, runner = self._send()
        self.assertEqual(result.reason, "USER_DESK_STALE")
        self.assertEqual(runner.threads(), [])

    def test_failed_send_to_desk_is_not_resent_to_a_guess(self):
        self._two_threads()
        deliver_module.register_user_desk(self.project, "codex", USER, source="test")

        class Failing(_Runner):
            def __call__(self, command, **kw):
                super().__call__(command, **kw)
                return mock.Mock(returncode=1, stdout="", stderr="boom")

        _result, runner = self._send(Failing())
        self.assertEqual(runner.threads(), [USER])

    def test_hook_registers_human_prompts_only(self):
        import contextlib
        import io

        from v7_harness.cli import main as cli_main

        self._two_threads()
        argv = ["coord", "presence", "--tool", "codex", "--state", "ACTIVE", "--from-hook", "--say", "none",
                "--project", str(self.project)]

        def prompt(text, session):
            event = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text,
                                "cwd": str(self.project)})
            with mock.patch("sys.stdin", io.StringIO(event)), contextlib.redirect_stdout(io.StringIO()):
                cli_main(argv)

        prompt("[UAOS relay id=r] work", BACKGROUND)
        self.assertEqual(deliver_module.read_user_desk(self.project, "codex"), "")
        prompt("윤겸스가 직접 쓴 지시", USER)
        self.assertEqual(deliver_module.read_user_desk(self.project, "codex"), USER)
        prompt("[DATA] from=sentinel", BACKGROUND)
        self.assertEqual(deliver_module.read_user_desk(self.project, "codex"), USER)
        _result, runner = self._send()
        self.assertEqual(runner.threads(), [USER])

    def test_invalid_desk_record_fails_closed_unlike_an_absent_one(self):
        # Codex relay_48fb8d38: only an ABSENT record allows the bootstrap guess; a present record that cannot be
        # read or holds no UUID stops with USER_DESK_STALE instead of handing the letter to a guessed window.
        self._two_threads()
        path = deliver_module.user_desk_path(self.project, "codex")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.assertEqual(deliver_module.user_desk_state(self.project, "codex"), ("ABSENT", ""))
        records = {"malformed JSON": "{", "not a dict": json.dumps([USER]), "thread not a str": '{"thread": 5}',
                   "non-UUID": '{"thread": "abc"}'}
        for name, text in records.items():
            with self.subTest(name):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(deliver_module.user_desk_state(self.project, "codex"), ("INVALID", ""))
                result, runner = self._send()
                self.assertEqual(result.reason, "USER_DESK_STALE")
                self.assertEqual(runner.threads(), [])
        path.unlink()
        path.mkdir()  # read failure: the record path is a directory
        self.assertEqual(deliver_module.user_desk_state(self.project, "codex"), ("INVALID", ""))
        result, runner = self._send()
        self.assertEqual(result.reason, "USER_DESK_STALE")
        self.assertEqual(runner.threads(), [])
        path.rmdir()
        with mock.patch.object(deliver_module.Path, "read_text", side_effect=PermissionError("denied")):
            self.assertEqual(deliver_module.user_desk_state(self.project, "codex"), ("INVALID", ""))

    def test_queued_letter_goes_to_the_desk_of_the_new_human_prompt(self):
        # Codex relay_48fb8d38: the hook used to mark ACTIVE (which sends queued letters) before registering the new
        # desk, so the user's first prompt in a new window flushed queued letters to the old desk.
        import contextlib
        import io

        from v7_harness.cli import main as cli_main
        from v7_harness.coord import presence

        self._two_threads()
        deliver_module.register_user_desk(self.project, "codex", BACKGROUND, source="test")
        presence.mark(self.project, "codex", "LIMITED")
        result, runner = self._send()
        self.assertEqual(result.reason, "QUEUED_UNTIL_ACTIVE")
        self.assertEqual(runner.threads(), [])
        event = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": USER, "prompt": "윤겸스 새 창 지시",
                            "cwd": str(self.project)})
        hook = _Runner()
        real_dispatch = presence._dispatch_queued

        def in_process(project, tool, _runner):
            # The hook normally sends from a detached process; run it here, at the same moment, with a stub runner.
            real_dispatch(project, tool, hook)

        with mock.patch("v7_harness.coord.presence._dispatch_queued", in_process), \
                mock.patch("sys.stdin", io.StringIO(event)), contextlib.redirect_stdout(io.StringIO()):
            cli_main(["coord", "presence", "--tool", "codex", "--state", "ACTIVE", "--from-hook", "--say", "none",
                      "--project", str(self.project)])
        self.assertEqual(deliver_module.read_user_desk(self.project, "codex"), USER)
        self.assertEqual(hook.threads(), [USER])


del UserWindowTest  # run the frozen tests once, from their own module

if __name__ == "__main__":
    unittest.main()
