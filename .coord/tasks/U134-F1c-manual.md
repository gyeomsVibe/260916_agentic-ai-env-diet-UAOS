```contract
work_id: U134-F1c
worker: apply
apply_after: U134-F1b
goal: cwd fail-closed validation and fixture alignment for U113/U115 under U134 (U134-F1c)
inputs:
- tests/test_u134_thread_fallback.py sha256=a272923674c458ba9e06fc364f3c69b0276c5415006d931ddab2f005e597d944
- tests/test_u134_judge_counterexamples.py sha256=019608228ca494af4c798d735c066bf6a182401ef5b338d8f7f3dbf265d52ad3
- tests/test_u134_f1b_cwd.py sha256=496a3bbdeceaac1aeb02af5652cbfaf98e0b990825ad6100d29360e593dc5930
- tests/test_u113_desk_truth.py sha256=c8ae91607a946fc8becf49d36c394f5c6f3f8ee1405bc1a7df5b0147bcdf0a96
- tests/test_u115_card_window_route.py sha256=9a4d83a67a2cbc44ec8d52260dbf84a9e9fae91994d0a7a7fb072941d739e75b
allow:
- v7_harness/coord/deliver.py
- tests/test_u113_desk_truth.py
- tests/test_u115_card_window_route.py
acceptance: python -m unittest tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples tests.test_u134_f1b_cwd tests.test_u113_desk_truth tests.test_u114_merge_relay tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread
forbidden: production behavior beyond F1b guard; deletion; main edits; promotion; commit/push; U144
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Work Order: U134-F1c Replacement Card

Receipt: Codex relay_f5c04117 REJECT of bundle f0d77aab.
Order: Codex relay_f5c04117, Claude relay_0d31b71a.
Base: stage .coord/pilot/stage/U134-F1 deliver.py 12a3d75d.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    cwd_str = payload.get("cwd")
    cwd = Path(cwd_str).resolve() if cwd_str else None
    return chosen_id, cwd, "OK"
=======
    if "cwd" in payload:
        cwd_val = payload["cwd"]
        if not isinstance(cwd_val, str) or not cwd_val.strip():
            return "", None, "THREAD_UNVERIFIED"
        cwd = Path(cwd_val).resolve()
    else:
        cwd = None
    return chosen_id, cwd, "OK"
>>>>>>> REPLACE

===EDIT: tests/test_u113_desk_truth.py===
<<<<<<< SEARCH
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.hook_context import agy_line, brief_line


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise OSError("codex not installed here")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class NoLetterWaitsInALimitedThread(_Isolated):
    def test_limited_or_absent_codex_gets_the_mailbox_only(self):
        for n, state in enumerate(("LIMITED", "ABSENT")):
            presence.mark(self.project, "codex", state)
            runner = _Recorder()
            with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
                result = deliver(self.project, message=f"U113 {state}", actor="claude", target="codex",
                                 runner=runner, thread="t1")
            # U134-C: still no dispatch while LIMITED/ABSENT, but the letter is queued for the next ACTIVE turn.
            self.assertEqual(("codex", "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason), state)
            self.assertEqual([], runner.calls, state)
            self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_active_codex_is_still_dispatched(self):
        presence.mark(self.project, "codex", "ACTIVE")
        runner = _Recorder()
        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
            deliver(self.project, message="U113 active", actor="claude", target="codex", runner=runner, thread="t1")
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
=======
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver
from v7_harness.coord.hook_context import agy_line, brief_line


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(command)
        raise OSError("codex not installed here")


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()


class NoLetterWaitsInALimitedThread(_Isolated):
    def test_limited_or_absent_codex_gets_the_mailbox_only(self):
        for n, state in enumerate(("LIMITED", "ABSENT")):
            presence.mark(self.project, "codex", state)
            runner = _Recorder()
            with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
                result = deliver(self.project, message=f"U113 {state}", actor="claude", target="codex",
                                 runner=runner, thread="t1")
            # U134-C: still no dispatch while LIMITED/ABSENT, but the letter is queued for the next ACTIVE turn.
            self.assertEqual(("codex", "QUEUED_UNTIL_ACTIVE"), (result.target, result.reason), state)
            self.assertEqual([], runner.calls, state)
            self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_active_codex_is_still_dispatched(self):
        presence.mark(self.project, "codex", "ACTIVE")
        runner = _Recorder()
        thread_id = "0199cccc-0000-7000-8000-000000000003"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{thread_id}.jsonl"
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": thread_id, "session_id": thread_id, "cwd": str(self.project)}}) + "\n", encoding="utf-8")
        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex"):
            deliver(self.project, message="U113 active", actor="claude", target="codex", runner=runner, thread=thread_id)
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
>>>>>>> REPLACE

===EDIT: tests/test_u115_card_window_route.py===
<<<<<<< SEARCH
        sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _window(self, card, **ids):
        path = self.project / ".coord" / "windows" / f"{card}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tools = {tool: {"id": window_id, "opened_at": 0} for tool, window_id in ids.items()}
        path.write_text(json.dumps({"card": card, "title": f"[{card}] t", "tools": tools}), encoding="utf-8")

    def _payload(self, result):
        letter = self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
        return json.loads(letter.read_text(encoding="utf-8"))["payload"]

    @staticmethod
    def _after(argv, flag):
        return argv[argv.index(flag) + 1]


class CodexWindow(_Isolated):
    def test_card_with_a_codex_window_queues_into_that_thread(self):
        presence.mark(self.project, "codex", "ACTIVE")
        self._window("U115", codex="thr-window")
        runner = _Runner()
        result = deliver(self.project, message="U115 codex window", actor="claude", target="codex",
                         thread="thr-default", runner=runner, card="U115")
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
        self.assertEqual("thr-window", self._after(runner.calls[0], "--thread"))
        payload = self._payload(result)
        self.assertEqual(("U115", "thr-window"), (payload["card"], payload["window"]))

    def test_without_card_or_without_a_window_the_default_thread_is_used(self):
        presence.mark(self.project, "codex", "ACTIVE")
        self._window("U115", codex="thr-window")
        for n, card in enumerate(("", "U999")):
            runner = _Runner()
            result = deliver(self.project, message=f"U115 default {n}", actor="claude", target="codex",
                             thread="thr-default", runner=runner, card=card)
            self.assertEqual("thr-default", self._after(runner.calls[0], "--thread"), card)
            payload = self._payload(result)
            if card:
                self.assertEqual(("U999", None), (payload["card"], payload.get("window")))
            else:  # no --card: today's payload bytes, unchanged
                self.assertNotIn("card", payload)
                self.assertNotIn("window", payload)
=======
        self.sessions = Path(self._tmp.name) / "codex-sessions"  # never the PC's real Codex logs
        self.sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _window(self, card, **ids):
        path = self.project / ".coord" / "windows" / f"{card}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tools = {tool: {"id": window_id, "opened_at": 0} for tool, window_id in ids.items()}
        path.write_text(json.dumps({"card": card, "title": f"[{card}] t", "tools": tools}), encoding="utf-8")

    def _payload(self, result):
        letter = self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
        return json.loads(letter.read_text(encoding="utf-8"))["payload"]

    @staticmethod
    def _after(argv, flag):
        return argv[argv.index(flag) + 1]


class CodexWindow(_Isolated):
    def test_card_with_a_codex_window_queues_into_that_thread(self):
        presence.mark(self.project, "codex", "ACTIVE")
        win_thread = "0199aaaa-0000-7000-8000-000000000001"
        def_thread = "0199bbbb-0000-7000-8000-000000000002"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        for tid in (win_thread, def_thread):
            (day / f"rollout-2026-10-03T06-00-00-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid, "session_id": tid, "cwd": str(self.project)}}) + "\n",
                encoding="utf-8",
            )
        self._window("U115", codex=win_thread)
        runner = _Runner()
        result = deliver(self.project, message="U115 codex window", actor="claude", target="codex",
                         thread=def_thread, runner=runner, card="U115")
        self.assertEqual(1, len(runner.calls))
        self.assertIn("queue", runner.calls[0])
        self.assertEqual(win_thread, self._after(runner.calls[0], "--thread"))
        payload = self._payload(result)
        self.assertEqual(("U115", win_thread), (payload["card"], payload["window"]))

    def test_without_card_or_without_a_window_the_default_thread_is_used(self):
        presence.mark(self.project, "codex", "ACTIVE")
        win_thread = "0199aaaa-0000-7000-8000-000000000001"
        def_thread = "0199bbbb-0000-7000-8000-000000000002"
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        for tid in (win_thread, def_thread):
            (day / f"rollout-2026-10-03T06-00-00-{tid}.jsonl").write_text(
                json.dumps({"type": "session_meta", "payload": {"id": tid, "session_id": tid, "cwd": str(self.project)}}) + "\n",
                encoding="utf-8",
            )
        self._window("U115", codex=win_thread)
        for n, card in enumerate(("", "U999")):
            runner = _Runner()
            result = deliver(self.project, message=f"U115 default {n}", actor="claude", target="codex",
                             thread=def_thread, runner=runner, card=card)
            self.assertEqual(def_thread, self._after(runner.calls[0], "--thread"), card)
            payload = self._payload(result)
            if card:
                self.assertEqual(("U999", None), (payload["card"], payload.get("window")))
            else:  # no --card: today's payload bytes, unchanged
                self.assertNotIn("card", payload)
                self.assertNotIn("window", payload)
>>>>>>> REPLACE
