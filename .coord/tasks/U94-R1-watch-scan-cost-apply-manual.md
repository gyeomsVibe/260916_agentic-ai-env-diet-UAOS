```contract
work_id: U94-R1
worker: apply
goal: Keep the 2 s watch interval from U94 but read only inbox letters the watch has not seen, so a scan costs a directory listing instead of re-reading every letter.
inputs:
- .coord/PLAN.md sha256=0f8138fa0046344768b004d89736409754efabe9f3caa49fc7a87961677a30af
- v7_harness/coord/watch.py sha256=2a304c1c05d0180c86ee197d8cf34edad5a75be1accbcb9bb57eec5fba42e3e6
- v7_harness/coord/mailbox.py sha256=04adccedc0d9e425b7ef883ebb5863cb5b89f01a7693db0be9cc4c7236fe1baf
- tests/test_u57_desk_signals.py sha256=ae27521c3ad65be0db9e59765438c8bdcd2cdd503fbc86143d19cd7eb75386ab
allow:
- v7_harness/coord/watch.py
- v7_harness/coord/mailbox.py
- tests/test_u94r1_watch_scan_cost.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u94r1_watch_scan_cost tests.test_u57_desk_signals tests.test_u64f_no_double_wake
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT and FILE blocks exactly.

Receipt (2026-09-30 audit of U94): `watch()` called `Mailbox.peek()` on every scan, and `peek()` reads and parses every inbox letter. On the desk, with 464 letters, one scan took a median of 132 ms. At 2 s per scan that is 1,800 scans an hour instead of 120, a 15x cost regression over the 30 s baseline, and the U94 gate never measured it. Listing names only takes 8.1 ms.

===EDIT: v7_harness/coord/mailbox.py===
<<<<<<< SEARCH
    def list_inbox(self) -> list[str]:
        return sorted([p.stem for p in self.inbox_dir.glob("*.json") if p.is_file()])

=======
    def list_inbox(self) -> list[str]:
        return sorted([p.stem for p in self.inbox_dir.glob("*.json") if p.is_file()])

    def read_message(self, message_id: str) -> dict | None:
        """One inbox letter without claiming it; None when it is gone (claimed) or unreadable."""
        return _read_message(self.inbox_dir / f"{message_id}.json")

>>>>>>> REPLACE
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
# 2 s between inbox scans: the hand-written loop used 30 s on 2026-09-27 and a letter waited at most that long;
# one scan lists one directory, so a shorter interval costs only disk reads, never tokens.
DEFAULT_INTERVAL_S = 2.0
=======
# 2 s between inbox scans (U94, 2026-09-30): a letter waits at most one interval before the watch wakes; the
# hand-written loop of 2026-09-27 used 30 s. A scan lists the inbox and reads only letters it has not seen (U94-R1):
# re-reading all 464 desk letters took 132 ms a scan, so 2 s kept a watcher busy 6.6% of the time (15x the 30 s
# cost); the listing alone took 8.1 ms (0.4%). Never tokens either way.
DEFAULT_INTERVAL_S = 2.0
>>>>>>> REPLACE
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
            for message_id, payload in box.peek():
                if message_id in seen:
                    continue
=======
            # U94-R1: decide on the name first and read a letter's file only when its id is new to this watch.
            for message_id in box.list_inbox():
                if message_id in seen:
                    continue
>>>>>>> REPLACE
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                if pending_live:
                    continue
                seen.add(message_id)
                if _addressed(payload, tools):
=======
                if pending_live:
                    continue
                data = box.read_message(message_id)
                if data is None:
                    continue  # claimed meanwhile, or not readable yet: the next scan looks again, as peek() did
                seen.add(message_id)
                payload = data.get("payload")
                if _addressed(payload, tools):
>>>>>>> REPLACE
===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`.coord/tasks/U94-instant-watch-manual.md` |
=======
`.coord/tasks/U94-instant-watch-manual.md` |
| U94-R1 | REVIEW (Claude 감사 2026-09-30: U94는 비용 관문 실패·자기 판정; Codex 복귀 시 재검토) | claude(감사·설계) · apply(0토큰) | 영수증: U94 뒤 `coord watch`가 2초마다 `peek()`로 받은 편지 464통 전부를 다시 읽음. 1회 132 ms, 시간당 1,800회로 30초 기준 대비 비용 15배(관문 3배 초과). U94 인수는 상수 2.0만 확인해 비용을 재지 않았고 판정자가 Antigravity 자신이었음. 조치: 이름 목록(8.1 ms)으로 먼저 거르고 새 편지만 읽음, 2초 간격 유지. — `v7_harness/coord/watch.py`, `v7_harness/coord/mailbox.py`, `tests/test_u94r1_watch_scan_cost.py` |
>>>>>>> REPLACE
===FILE: tests/test_u94r1_watch_scan_cost.py===
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
===END===

## Output

- Reply with ===EDIT and ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
