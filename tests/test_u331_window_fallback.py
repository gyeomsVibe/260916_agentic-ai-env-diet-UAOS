"""U331-F: a card window that fails thread verification falls back to the verified user desk (never a guess).

Receipt (2026-11-20, twice): `deliver --card X --target codex` replaced the thread with the card's window, the registry
entry pointed at a thread whose rollout cwd was another project, `_verify_thread` said THREAD_PROJECT_MISMATCH and the
letter failed closed although a verified designated desk existed. Fixed acceptance: mismatched/unverified window ->
stale entry released + desk fallback with a `thread_fallback` record; no verified desk -> still fails closed;
`record_window` refuses a Codex thread whose rollout cwd is outside the registered roots. No paid session starts.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import presence, windows
from v7_harness.coord.deliver import deliver

WIN = "0199aaaa-0000-7000-8000-000000000001"
DESK = "0199bbbb-0000-7000-8000-000000000002"


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")


class Fallback(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.project = root / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.foreign = root / "other-project"
        self.foreign.mkdir()
        self.sessions = root / "codex-sessions"
        (self.sessions / "2026" / "11" / "20").mkdir(parents=True)
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "codex", "ACTIVE")

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _rollout(self, thread, cwd):
        path = self.sessions / "2026" / "11" / "20" / f"rollout-2026-11-20T06-00-00-{thread}.jsonl"
        path.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": thread, "session_id": thread, "cwd": str(cwd)}}) + "\n",
            encoding="utf-8",
        )

    def _desk(self, thread):
        path = self.project / ".coord" / "presence" / "user_desk_codex.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"thread": thread}), encoding="utf-8")

    def _window(self, card, thread):
        path = self.project / ".coord" / "windows" / f"{card}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"card": card, "title": f"[{card}] t", "tools": {"codex": {"id": thread, "opened_at": 0}}}),
                        encoding="utf-8")

    def _send(self):
        runner = _Runner()
        result = deliver(self.project, message="U331 card letter", actor="claude", target="codex", runner=runner,
                         card="U331")
        return runner, result

    def _receipt(self, result):
        files = sorted((self.project / ".coord" / "mailbox" / "delivery").rglob(f"{result.message_id}*.json"))
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("thread_fallback"):
                return data
        return {}

    def test_mismatched_card_window_falls_back_to_the_verified_desk(self):
        self._rollout(WIN, self.foreign)
        self._rollout(DESK, self.project)
        self._desk(DESK)
        self._window("U331", WIN)
        runner, result = self._send()
        self.assertEqual("DISPATCHED", result.reason)
        self.assertEqual(DESK, runner.calls[0][runner.calls[0].index("--thread") + 1])
        letter = self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json"
        payload = json.loads(letter.read_text(encoding="utf-8"))["payload"]
        self.assertEqual(DESK, payload.get("window"))  # Codex P1: the published envelope names the desk, not the stale window
        sent = " ".join(runner.calls[0])  # the dispatched envelope: route, payload and ACK consumer share one receiver
        self.assertIn(f"Native receiver {DESK}", sent)
        self.assertIn(f"--consumer {DESK}", sent)
        self.assertNotIn(WIN, sent)
        entry = windows.window_entry(self.project, "U331", "codex")
        self.assertEqual("RELEASED", entry.get("state"))
        receipt = self._receipt(result)
        self.assertEqual(
            {"given": WIN, "used": DESK, "why": "card_window_THREAD_PROJECT_MISMATCH"}, receipt.get("thread_fallback"))

    def test_unverified_card_window_falls_back_the_same_way(self):
        self._rollout(DESK, self.project)  # the window thread has no rollout at all
        self._desk(DESK)
        self._window("U331", WIN)
        runner, result = self._send()
        self.assertEqual("DISPATCHED", result.reason)
        self.assertEqual(DESK, runner.calls[0][runner.calls[0].index("--thread") + 1])
        receipt = self._receipt(result)
        self.assertEqual("card_window_THREAD_UNVERIFIED", receipt["thread_fallback"]["why"])

    def test_no_verified_desk_still_fails_closed(self):
        self._rollout(WIN, self.foreign)
        self._rollout(DESK, self.project)  # a candidate exists but is NOT the designated desk: never guessed
        self._window("U331", WIN)
        runner, result = self._send()
        self.assertFalse(result.delivered)
        self.assertEqual([], runner.calls)
        self.assertIn(result.reason, ("THREAD_PROJECT_MISMATCH", "THREAD_UNVERIFIED"))

    def test_desk_that_is_itself_unverified_fails_closed(self):
        self._rollout(WIN, self.foreign)
        self._desk(DESK)  # designated, but its rollout is missing
        self._window("U331", WIN)
        runner, result = self._send()
        self.assertFalse(result.delivered)
        self.assertEqual([], runner.calls)

    def test_record_window_rejects_a_foreign_codex_cwd(self):
        self._rollout(WIN, self.foreign)
        with self.assertRaises(windows.ForeignCodexThread):
            windows.record_window(self.project, "U331", "codex", WIN)
        self.assertFalse((self.project / ".coord" / "windows" / "U331.json").exists())

    def test_no_rollout_and_no_desk_fails_closed_and_keeps_the_entry(self):
        self._rollout(DESK, self.project)  # a guessable newest thread exists, but no designated desk
        self._window("U331", WIN)  # WIN has no rollout at all
        runner, result = self._send()
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)  # never the guessed newest thread
        self.assertEqual(WIN, windows.window_entry(self.project, "U331", "codex")["id"])
        self.assertNotEqual("RELEASED", windows.window_entry(self.project, "U331", "codex").get("state"))

    def test_fallback_releases_the_stale_entry_with_its_reason(self):
        self._rollout(WIN, self.foreign)
        self._rollout(DESK, self.project)
        self._desk(DESK)
        self._window("U331", WIN)
        self._send()
        entry = windows.window_entry(self.project, "U331", "codex")
        self.assertEqual("STALE_CARD_WINDOW:THREAD_PROJECT_MISMATCH", entry.get("release_reason"))
        runner, result = self._send()  # next letter: the released entry is not re-read, no stale fallback record
        self.assertEqual("DISPATCHED", result.reason)
        self.assertEqual({}, self._receipt(result))

    def test_record_window_keeps_a_released_foreign_record(self):
        self._rollout(WIN, self.foreign)
        windows.record_window(self.project, "U331", "codex", WIN, state="RELEASED")
        windows.record_window(self.project, "U331", "codex", WIN, released_at=1.0)
        self.assertEqual(WIN, windows.window_entry(self.project, "U331", "codex")["id"])

    def test_record_window_accepts_a_thread_inside_the_project(self):
        self._rollout(DESK, self.project)
        windows.record_window(self.project, "U331", "codex", DESK)
        self.assertEqual(DESK, windows.window_entry(self.project, "U331", "codex")["id"])


if __name__ == "__main__":
    unittest.main()
