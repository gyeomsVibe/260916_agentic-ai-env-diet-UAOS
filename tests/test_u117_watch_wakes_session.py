"""U117: a watcher that wakes its own session takes every letter for Claude, so no headless paid turn answers it.

Receipt (2026-10-01): the U115 window reported to the conductor with `coord deliver --target claude` and an
ACTIONABLE_DELTA. U64 dispatches every real delta to the headless delivery session (`claude -p --resume`, Read only)
even while a watcher is live, because a plain `coord watch` cannot start an AI turn. So the letter got an accepted
receipt, the conductor's watcher skipped it (U64-F), and the conductor never woke; the headless session answered it
instead. That session's transcript is 2.6 MB and it was resumed 105 times (09-27..10-01, 10 today). In Claude Code a
background `coord watch` does wake its session when it exits, so such a watcher declares `--wakes-session` in its
heartbeat and deliver then queues the letter for it (0 paid turns). Watchers without the flag keep U64 exactly.
Fixed acceptance written by the judge (claude) first; no paid call.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.cli import build_parser
from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.watch import watch, watch_file, watcher_wakes


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


class WatchWakesSession(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "claude", "ACTIVE")

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _heartbeat(self, *, wakes, expires_in=120.0):
        path = watch_file(self.project, "claude")
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + expires_in}
        if wakes is not None:
            body["wakes_session"] = wakes
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_a_waking_watcher_takes_a_real_delta_without_a_paid_turn(self):
        self._heartbeat(wakes=True)
        runner = _Runner()
        result = deliver(self.project, message="U115 window done ACTIONABLE_DELTA verdict_requested=yes",
                         actor="claude", target="claude", runner=runner)
        self.assertEqual("QUEUED_INTERACTIVE", result.reason)
        self.assertEqual([], runner.calls)
        self.assertTrue(watcher_wakes(self.project, "claude"))

    def test_a_plain_watcher_keeps_the_u64_dispatch(self):
        for wakes in (None, False):
            self._heartbeat(wakes=wakes)
            runner = _Runner()
            result = deliver(self.project, message=f"plain {wakes} ACTIONABLE_DELTA", actor="codex",
                             target="claude", runner=runner)
            self.assertEqual(1, len(runner.calls), wakes)
            self.assertNotEqual("QUEUED_INTERACTIVE", result.reason, wakes)
            self.assertFalse(watcher_wakes(self.project, "claude"), wakes)

    def test_an_expired_waking_watcher_does_not_hold_letters(self):
        self._heartbeat(wakes=True, expires_in=-1.0)
        runner = _Runner()
        deliver(self.project, message="late ACTIONABLE_DELTA", actor="codex", target="claude", runner=runner)
        self.assertEqual(1, len(runner.calls))
        self.assertFalse(watcher_wakes(self.project, "claude"))

    def test_the_cli_flag_reaches_the_heartbeat(self):
        args = build_parser().parse_args(["coord", "watch", "--project", str(self.project), "--target", "claude",
                                          "--wakes-session"])
        self.assertTrue(args.wakes_session)
        self.assertFalse(build_parser().parse_args(["coord", "watch", "--target", "claude"]).wakes_session)
        seen = {}

        def sleep(_s):
            seen["beat"] = json.loads(watch_file(self.project, "claude").read_text(encoding="utf-8"))

        moments = iter([0.0, 0.0, 0.0, 10.0, 10.0, 10.0])
        watch(self.project, ("claude",), timeout_s=5.0, interval_s=1.0, clock=lambda: next(moments, 99.0),
              sleep=sleep, wakes_session=True)
        self.assertIs(True, seen["beat"]["wakes_session"])


if __name__ == "__main__":
    unittest.main()
