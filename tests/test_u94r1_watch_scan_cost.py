"""U94-R1: a watch scan reads only letters it has not seen, so the 2 s interval of U94 costs a directory listing.

Seen 2026-09-30: after U94 cut the interval from 30 s to 2 s, every scan still re-read and parsed all 464 desk inbox
letters (132 ms a scan, 15x the 30 s cost). Letters waiting when the watch starts are never reported, so reading them
again on every scan was pure cost.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord import mailbox as mailbox_module
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch

# 40 letters waiting and 5 scans: the old code reads 200+ files, the fix reads only the one new letter.
OLD_LETTERS = 40
SCANS_BEFORE_NEW = 5


class WatchScanCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.project / ".coord" / "mailbox")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _letter(self, message_id: str, target: str) -> None:
        self.box.publish(message_id, {"kind": "NOTE", "actor": "codex", "requested_target": target, "message": "x"})

    def test_waiting_letters_are_not_reread_on_every_scan(self) -> None:
        for n in range(OLD_LETTERS):
            self._letter(f"old_{n:03d}", "claude")
        ticks = {"n": 0}

        def sleep(_s: float) -> None:
            ticks["n"] += 1
            if ticks["n"] == SCANS_BEFORE_NEW:
                self._letter("new_for_claude", "claude")

        real = mailbox_module._read_message
        reads: list[str] = []

        def counting(path: Path):
            reads.append(Path(path).stem)
            return real(path)

        with patch.object(mailbox_module, "_read_message", side_effect=counting):
            found = watch(self.project, ("claude",), timeout_s=60, interval_s=1, sleep=sleep)
        self.assertEqual("new_for_claude", found["id"])
        self.assertEqual(reads, ["new_for_claude"])

    def test_a_letter_that_cannot_be_read_yet_is_retried_on_the_next_scan(self) -> None:
        ticks = {"n": 0}
        real = mailbox_module._read_message

        def flaky(path: Path):
            # The first read of the new letter fails as if it were mid-write; the next scan must read it again.
            if Path(path).stem == "late" and ticks["n"] == 1:
                return None
            return real(path)

        def sleep(_s: float) -> None:
            ticks["n"] += 1
            if ticks["n"] == 1:
                self._letter("late", "claude")

        with patch.object(mailbox_module, "_read_message", side_effect=flaky):
            found = watch(self.project, ("claude",), timeout_s=60, interval_s=1, sleep=sleep)
        self.assertEqual("late", found["id"])


if __name__ == "__main__":
    unittest.main()
