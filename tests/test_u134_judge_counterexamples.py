"""Supplemental judge gate for U134-R F1 counterexamples (relay_59db4000, relay_a7ee1f61).

Tests:
1. Empty present id key with valid session_id fails closed (THREAD_UNVERIFIED).
2. Valid id with empty present session_id fails closed (THREAD_UNVERIFIED).
3. Null or non-string id values fail closed (THREAD_UNVERIFIED).
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


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return mock.Mock(returncode=0, stdout="", stderr="")


class JudgeCounterexamplesTest(unittest.TestCase):
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

    def _rollout(self, thread, cwd, age_s, meta_dict):
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{thread}.jsonl"
        path.write_text(json.dumps(meta_dict) + "\n", encoding="utf-8")
        moment = time.time() - age_s
        os.utime(path, (moment, moment))
        return path

    def _send(self, thread, message, runner=None):
        runner = runner or _Runner()
        result = deliver(self.project, message=message, actor="claude", target="codex", runner=runner, thread=thread)
        return result, runner

    def test_empty_present_id_fails_closed(self):
        bad_meta = {"type": "session_meta", "payload": {"id": "", "session_id": OLD, "cwd": str(self.project)}}
        self._rollout(OLD, self.project, 10, bad_meta)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA empty present id")
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)

    def test_empty_present_session_id_fails_closed(self):
        bad_meta = {"type": "session_meta", "payload": {"id": OLD, "session_id": "", "cwd": str(self.project)}}
        self._rollout(OLD, self.project, 10, bad_meta)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA empty present session_id")
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)

    def test_none_id_value_fails_closed(self):
        bad_meta = {"type": "session_meta", "payload": {"id": None, "session_id": OLD, "cwd": str(self.project)}}
        self._rollout(OLD, self.project, 10, bad_meta)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA null id")
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)


if __name__ == "__main__":
    unittest.main()
