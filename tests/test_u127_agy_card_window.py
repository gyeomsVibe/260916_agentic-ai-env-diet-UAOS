"""U127: one Antigravity conversation per card, so a card's audit, re-audit and replies stay in one window.

Receipts (2026-10-02):
- The user: "the one-window-per-process logic was to apply to all three tools, but nothing changed". `.coord/windows/`
  held one record (U115, claude only); every U120 auto reply ran in a fresh Antigravity conversation, so U124-A,
  U124-A2, U125-A and U126-A each got their own conversation.
- Probe: `agy -p --conversation af19c18f-…` (the U126-A audit) answered "U126-A: REVISE" in the same conversation,
  with 53,072 input tokens against about 25,000 for a fresh turn, so resuming has a cost cap.
Fixed acceptance written by the judge (claude) before the run.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence, windows
from v7_harness.coord.deliver import deliver
from v7_harness.coord.watch import watch_file

LETTER = "[review] verdict_requested=yes ACTIONABLE_DELTA: check diff X"


class CardWindowRecordTest(unittest.TestCase):
    def test_record_keeps_the_other_tools_windows(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            windows.record_window(root, "U9", "claude", "b5a6062d")
            windows.record_window(root, "U9", "antigravity", "conv-1", last_input_tokens=30_000)
            self.assertEqual("b5a6062d", windows.window_for(root, "U9", "claude"))
            entry = windows.window_entry(root, "U9", "antigravity")
            self.assertEqual("conv-1", entry["id"])
            self.assertEqual(30_000, entry["last_input_tokens"])
            self.assertEqual({}, windows.window_entry(root, "U8", "antigravity"))

    def test_bad_card_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                windows.record_window(Path(d), "../x", "antigravity", "conv-1")

    def test_parallel_writers_never_corrupt_the_record(self) -> None:
        # U127-A audit: two letters for one card can record at once; each writer must leave a whole JSON record.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            barrier = threading.Barrier(8)
            errors: list[BaseException] = []

            def write(i: int) -> None:
                try:
                    barrier.wait()
                    for n in range(10):
                        windows.record_window(root, "U9", f"tool{i}", f"conv-{i}-{n}", last_input_tokens=n)
                        windows.window_entry(root, "U9", f"tool{i}")
                except BaseException as exc:  # collected so the main thread fails the test
                    errors.append(exc)

            threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual([], errors)
            record = json.loads((root / ".coord" / "windows" / "U9.json").read_text(encoding="utf-8"))
            self.assertEqual("U9", record["card"])
            self.assertTrue(record["tools"])
            self.assertEqual([], list((root / ".coord" / "windows").glob("*.tmp")))


class AgyCardConversationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        os.environ.pop("UAOS_AGY_AUTO", None)
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", side_effect=lambda name: name)
        self._which.start()
        presence.mark(self.project, "claude", "ACTIVE")
        beat = watch_file(self.project, "claude")  # a session-waking Claude watcher takes the reply (U117)
        beat.parent.mkdir(parents=True, exist_ok=True)
        beat.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": time.time() + 300,
                                    "wakes_session": True}), encoding="utf-8")
        self.calls: list[list[str]] = []
        self.conversation = "conv-new"
        self.broken_resume = False

    def tearDown(self) -> None:
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        if Path(argv[0]).stem != "agy":
            raise AssertionError(f"only agy may run here: {argv[0]}")
        if self.broken_resume and "--conversation" in argv:  # an expired or deleted conversation id
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"conversation not found")
        envelope = {"status": "SUCCESS", "conversation_id": self.conversation,
                    "usage": {"input_tokens": 25_000, "output_tokens": 900}, "response": "PASS: matches the contract."}
        return SimpleNamespace(returncode=0, stdout=json.dumps(envelope).encode("utf-8"), stderr=b"")

    def send(self, card: str = "U9", message: str = LETTER):
        return deliver(self.project, message=message, actor="claude", target="antigravity", runner=self.runner,
                       card=card)

    def _resumed(self) -> str | None:
        argv = self.calls[0]
        return argv[argv.index("--conversation") + 1] if "--conversation" in argv else None

    def test_first_card_letter_opens_and_records_the_window(self) -> None:
        self.send()
        self.assertIsNone(self._resumed())
        entry = windows.window_entry(self.project, "U9", "antigravity")
        self.assertEqual("conv-new", entry["id"])
        self.assertEqual(25_000, entry["last_input_tokens"])

    def test_next_card_letter_resumes_the_window(self) -> None:
        windows.record_window(self.project, "U9", "antigravity", "conv-1", last_input_tokens=50_000)
        self.conversation = "conv-1"
        self.send(message=LETTER + " second")
        self.assertEqual("conv-1", self._resumed())
        self.assertEqual("conv-1", windows.window_for(self.project, "U9", "antigravity"))

    def test_heavy_window_starts_a_fresh_conversation(self) -> None:
        windows.record_window(self.project, "U9", "antigravity", "conv-1",
                              last_input_tokens=agy_dispatch.RESUME_MAX_INPUT)
        self.send()
        self.assertIsNone(self._resumed())
        self.assertEqual("conv-new", windows.window_for(self.project, "U9", "antigravity"))

    def test_resume_cap_leaves_room_for_one_more_turn(self) -> None:
        # U127-A audit: a resumed turn grew the input by about 28,000 (25,000 fresh, 53,072 resumed), and the next
        # turn must still fit the 100,000 review budget, so the cap is at most 72,000.
        self.assertLessEqual(agy_dispatch.RESUME_MAX_INPUT + 28_000, 100_000)

    def test_broken_window_retries_once_in_a_fresh_conversation(self) -> None:
        windows.record_window(self.project, "U9", "antigravity", "conv-gone", last_input_tokens=30_000)
        self.broken_resume = True
        self.send()
        last = agy_dispatch._ledger(self.project).read_text(encoding="utf-8").splitlines()[-1]
        self.assertEqual("ANSWERED", json.loads(last)["state"])
        agy_calls = [argv for argv in self.calls if Path(argv[0]).stem == "agy"]
        self.assertEqual(2, len(agy_calls))
        self.assertIn("--conversation", agy_calls[0])
        self.assertNotIn("--conversation", agy_calls[1])
        self.assertEqual("conv-new", windows.window_for(self.project, "U9", "antigravity"))

    def test_other_cards_and_tools_are_untouched(self) -> None:
        windows.record_window(self.project, "U9", "claude", "b5a6062d")
        windows.record_window(self.project, "U8", "antigravity", "conv-8", last_input_tokens=10_000)
        self.send()
        self.assertIsNone(self._resumed())
        self.assertEqual("b5a6062d", windows.window_for(self.project, "U9", "claude"))
        self.assertEqual("conv-8", windows.window_for(self.project, "U8", "antigravity"))

    def test_letter_without_card_records_no_window(self) -> None:
        self.send(card="")
        self.assertIsNone(self._resumed())
        self.assertFalse((self.project / ".coord" / "windows").exists())


if __name__ == "__main__":
    unittest.main()
