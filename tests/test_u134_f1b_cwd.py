"""Supplemental judge gate for U134-F1b (Codex relay_d60c4681 REJECT of bundle 0730b80e).

Receipt: a session_meta payload with cwd=123 raised TypeError at deliver.py:505 (Path(123).resolve()) instead of
failing closed. Rule: when the cwd key is present it must be a non-empty string; otherwise the rollout is
THREAD_UNVERIFIED with zero sends. Frozen by the coordinator before dispatch; red on deliver.py 12a3d75d.
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


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return mock.Mock(returncode=0, stdout="", stderr="")


class F1bCwdTest(unittest.TestCase):
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

    def _rollout(self, cwd_value):
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{OLD}.jsonl"
        meta = {"type": "session_meta", "payload": {"id": OLD, "session_id": OLD, "cwd": cwd_value}}
        path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
        moment = time.time() - 10
        os.utime(path, (moment, moment))

    def _assert_fails_closed(self, cwd_value):
        self._rollout(cwd_value)
        runner = _Runner()
        result = deliver(self.project, message="ACTIONABLE_DELTA bad cwd", actor="claude", target="codex",
                         runner=runner, thread=OLD)
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)

    def test_integer_cwd_fails_closed(self):
        self._assert_fails_closed(123)

    def test_list_cwd_fails_closed(self):
        self._assert_fails_closed([])

    def test_object_cwd_fails_closed(self):
        self._assert_fails_closed({"path": "x"})

    def test_blank_cwd_fails_closed(self):
        self._assert_fails_closed("   ")


if __name__ == "__main__":
    unittest.main()
