"""U61 frozen acceptance (written by Claude): a live `coord watch` receives auto-routed mail after the heartbeat expires.

The Claude session heartbeat lasts an hour after the last prompt; an overnight wait let it expire while the watcher
kept beating, and an auto-routed letter then stayed in the mailbox (PUBLISHED, mailbox_only) with nothing to wake.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.watch import watch_file


class _NoColdStart:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise AssertionError("no cold session may start")


class WatcherRoutesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        # U113: presence.read turns an ACTIVE codex into LIMITED when the PC's real Codex log holds a newer refusal;
        # on 2026-10-01 a real refusal landed mid-run and failed test_active_codex_still_comes_first once.
        sessions = self.project / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _live_watch(self):
        target = watch_file(self.project, "claude")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"tool": "claude", "token": "t", "expires_at": time.time() + 300}),
                          encoding="utf-8")

    def test_expired_heartbeat_with_live_watcher_is_queued_for_claude(self):
        presence.mark(self.project, "claude", "ACTIVE", ttl_s=1, now=time.time() - 7200)
        self._live_watch()
        runner = _NoColdStart()
        result = deliver(self.project, message="U61", actor="antigravity", runner=runner)
        self.assertEqual(("claude", "QUEUED_INTERACTIVE"), (result.target, result.reason))
        self.assertEqual([], runner.calls)

    def test_no_heartbeat_and_no_watcher_stays_mailbox_only(self):
        result = deliver(self.project, message="U61 none", actor="antigravity", runner=_NoColdStart())
        self.assertEqual(("mailbox_only", "PUBLISHED"), (result.target, result.reason))

    def test_active_codex_still_comes_first(self):
        presence.mark(self.project, "codex", "ACTIVE")
        self._live_watch()
        calls = []

        def runner(command, **_kw):
            calls.append(command)
            raise OSError("codex not installed here")

        result = deliver(self.project, message="U61 codex", actor="antigravity", runner=runner, thread="t1")
        self.assertEqual("codex", result.target)


if __name__ == "__main__":
    unittest.main()
