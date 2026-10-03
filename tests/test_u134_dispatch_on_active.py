"""U134-B/C: a letter to a LIMITED/ABSENT tool is queued until that tool is ACTIVE, then dispatched exactly once.

Receipt (2026-10-03, P1): `coord deliver --target codex` while the desk said LIMITED returned `mailbox_only`
PUBLISHED with no warning, and nothing re-sent the letter when Codex came back; Codex never saw relay_18758c37.
Now deliver answers QUEUED_UNTIL_ACTIVE, and the first ACTIVE heartbeat that asks for it (`dispatch=True`, the hook
path) sends each queued letter into the tool's thread once; two heartbeats really in parallel still send one.
Fixed acceptance written by the judge; the runner is a stub, so no real `codex queue` runs.
"""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver

THREAD = "01a1006f-4196-7ff0-87ac-f6523066cd8c"


class _Runner:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, command, **_kw):
        with self._lock:
            self.calls.append(list(command))
        return mock.Mock(returncode=0, stdout="", stderr="")


class DispatchOnActiveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True)
        # A live Codex thread of this project, so the given thread id is kept (U134-D falls back only otherwise).
        (day / f"rollout-2026-10-03T06-24-00-{THREAD}.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"session_id": THREAD, "cwd": str(self.project)}}) + "\n",
            encoding="utf-8")
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex")
        self._which.start()
        presence.mark(self.project, "codex", "LIMITED", ttl_s=86400, lease=True)

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _queued(self):
        runner = _Runner()
        result = deliver(self.project, message="ACTIONABLE_DELTA U134 handoff", actor="claude", target="codex",
                         runner=runner, thread=THREAD)
        self.assertEqual(("codex", "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason))
        self.assertEqual([], runner.calls)
        return result

    def test_a_letter_to_a_limited_tool_is_queued_not_silently_mailed(self):
        result = self._queued()
        self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_the_first_active_turn_dispatches_it_once(self):
        result = self._queued()
        runner = _Runner()
        presence.mark(self.project, "codex", "ACTIVE", session="s1", turn_start=True, dispatch=True, runner=runner)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
        self.assertEqual(THREAD, runner.calls[0][runner.calls[0].index("--thread") + 1])
        self.assertIn(result.message_id, runner.calls[0][-1])
        presence.mark(self.project, "codex", "ACTIVE", session="s1", turn_start=True, dispatch=True, runner=runner)
        self.assertEqual(1, len(runner.calls))  # already dispatched: never twice

    def test_two_parallel_heartbeats_dispatch_once(self):
        self._queued()
        presence.mark(self.project, "codex", "ACTIVE", session="s0", turn_start=True)  # clears the lease, no dispatch
        runner = _Runner()
        barrier = threading.Barrier(2)
        errors = []

        def beat(session):
            try:
                barrier.wait(timeout=10)
                presence.mark(self.project, "codex", "ACTIVE", session=session, dispatch=True, runner=runner)
            except Exception as exc:  # surfaced below; a thread exception would otherwise vanish
                errors.append(exc)

        threads = [threading.Thread(target=beat, args=(f"s{i}",)) for i in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual([], errors)
        self.assertEqual(1, len(runner.calls))

    def test_a_heartbeat_without_dispatch_or_while_limited_sends_nothing(self):
        self._queued()
        runner = _Runner()
        presence.mark(self.project, "codex", "LIMITED", session="s1", dispatch=True, runner=runner)
        presence.mark(self.project, "codex", "ACTIVE", session="s1", turn_start=True, runner=runner)
        self.assertEqual([], runner.calls)

    def test_a_failed_dispatch_stays_queued_for_the_next_heartbeat(self):
        self._queued()
        presence.mark(self.project, "codex", "ACTIVE", session="s0", turn_start=True)

        def failing(command, **_kw):
            return mock.Mock(returncode=1, stdout="", stderr="busy")

        presence.mark(self.project, "codex", "ACTIVE", session="s1", dispatch=True, runner=failing)
        runner = _Runner()
        presence.mark(self.project, "codex", "ACTIVE", session="s1", dispatch=True, runner=runner)
        self.assertEqual(1, len(runner.calls))


if __name__ == "__main__":
    unittest.main()
