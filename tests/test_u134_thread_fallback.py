"""U134-D: `--thread` that is not a live Codex thread falls back to the newest thread of this project.

Receipt (2026-10-03): `coord deliver --thread handoff-20261003` (a free-text name) failed `No active session found`;
only the real thread id worked. A thread is live when a Codex rollout file carries its id; otherwise the newest
rollout whose head names this project is used and the fallback is logged in the attempt receipt. With no project
thread at all the given value is kept (no worse than before). Fixed acceptance written by the judge; stub runner.
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

OLD = "0199aaaa-0000-7000-8000-000000000001"
NEW = "0199bbbb-0000-7000-8000-000000000002"
OTHER = "0199cccc-0000-7000-8000-000000000003"


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return mock.Mock(returncode=0, stdout="", stderr="")


class ThreadFallbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex")
        self._which.start()
        presence.mark(self.project, "codex", "ACTIVE")

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _rollout(self, thread, cwd, age_s):
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{thread}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"session_id": thread, "cwd": str(cwd)}}) + "\n",
                        encoding="utf-8")
        moment = time.time() - age_s
        os.utime(path, (moment, moment))

    def _thread_sent(self, thread, message):
        runner = _Runner()
        result = deliver(self.project, message=message, actor="claude", target="codex", runner=runner, thread=thread)
        self.assertEqual("DISPATCHED", result.reason, result)
        return runner.calls[0][runner.calls[0].index("--thread") + 1], result

    def test_a_bogus_thread_resolves_to_the_newest_project_thread(self):
        self._rollout(OLD, self.project, 300)
        self._rollout(NEW, self.project, 10)
        self._rollout(OTHER, Path(self._tmp.name) / "elsewhere", 1)  # newer, but another project
        sent, result = self._thread_sent("handoff-20261003", "ACTIONABLE_DELTA bogus thread")
        self.assertEqual(NEW, sent)
        receipt = json.loads(Path(result.receipt).read_text(encoding="utf-8"))
        self.assertEqual({"given": "handoff-20261003", "used": NEW}, receipt["thread_fallback"])

    def test_a_live_thread_id_is_kept(self):
        self._rollout(OLD, self.project, 300)
        self._rollout(NEW, self.project, 10)
        sent, result = self._thread_sent(OLD, "ACTIONABLE_DELTA live thread")
        self.assertEqual(OLD, sent)
        receipt = json.loads(Path(result.receipt).read_text(encoding="utf-8"))
        self.assertNotIn("thread_fallback", receipt)

    def test_with_no_project_thread_the_given_value_is_kept(self):
        self._rollout(OTHER, Path(self._tmp.name) / "elsewhere", 1)
        sent, _ = self._thread_sent("t1", "ACTIONABLE_DELTA no project thread")
        self.assertEqual("t1", sent)


if __name__ == "__main__":
    unittest.main()
