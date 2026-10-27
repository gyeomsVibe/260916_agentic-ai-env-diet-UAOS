"""U260: a BLOCKED letter is also cleared when the master schedule closed its card after the letter was written.

Seen 2026-10-27 (10 P1 wakes in the inbox, wake_a8984986… and nine siblings): the wake listed U169, U166-SELFLOOP,
U241C-S4, U251 and 170 more steps from 212 BLOCKED letters, although `.coord/master_schedule.json` marks their cards
DONE / DONE_SCOPED / DONE_ELSEWHERE / RETIRED. U88/U116 only read ledger PASS rows, and most of those cards closed
through a merged PR, never a pilot PASS, so every new BLOCKED letter re-fingerprinted the same stale list into a new
wake. The U88 and U116 acceptance stays unchanged. Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

BLOCKED_AT = "2026-10-01T10:00:00+09:00"
BEFORE = datetime.fromisoformat(BLOCKED_AT).timestamp() - 60
AFTER = datetime.fromisoformat(BLOCKED_AT).timestamp() + 60
AFTER_ISO = "2026-10-01T01:01:00+00:00"  # 60 s after BLOCKED_AT


def _project(directory: str, schedule: dict | str | None) -> tuple[Path, Mailbox]:
    root = Path(directory)
    (root / ".coord" / "mailbox").mkdir(parents=True)
    (root / ".coord" / "usage").mkdir(parents=True)
    (root / ".coord" / "usage" / "runs.jsonl").write_text("", encoding="utf-8")
    if schedule is not None:
        text = schedule if isinstance(schedule, str) else json.dumps(schedule)
        (root / ".coord" / "master_schedule.json").write_text(text, encoding="utf-8")
    return root, Mailbox(root / ".coord" / "mailbox")


def _blocked(step: str, **extra) -> dict:
    return {"kind": "BLOCKED", "step": step, "ts": BLOCKED_AT, "actor": "claude", **extra}


class ScheduleSupersededTests(unittest.TestCase):
    def test_terminal_phase_closed_after_the_letter_clears_step_and_sub_steps(self) -> None:
        schedule = {"updated_at": AFTER_ISO, "phases": [
            {"phase_id": "U169", "state": "DONE", "updated_at": AFTER},
            {"phase_id": "U241C", "state": "DONE", "updated_at": AFTER_ISO},
            {"phase_id": "U236a", "state": "DONE_SCOPED", "updated_at": AFTER},
            {"phase_id": "U191-U185-FREEZE", "state": "DONE_ELSEWHERE", "updated_at": AFTER},
            {"phase_id": "U185-CONTRACT-REVIEW", "state": "RETIRED"},  # no own time: schedule updated_at counts
        ]}
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, schedule)
            steps = ("U169", "U241C-S4", "U236A-L2", "U191-U185-FREEZE", "U185-CONTRACT-REVIEW")
            for step in steps:
                box.publish(f"b-{step}", _blocked(step))
            result = run_sentinel_cycle(root, box)
            self.assertFalse(result["p1_wake_emitted"])
            self.assertEqual(sorted(steps), sorted(result["p1_superseded"]))

    def test_open_or_earlier_closed_phase_keeps_the_alert(self) -> None:
        schedule = {"updated_at": AFTER_ISO, "phases": [
            {"phase_id": "U259", "state": "READY", "updated_at": AFTER},
            {"phase_id": "U251", "state": "DONE", "updated_at": BEFORE},
        ]}
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, schedule)
            box.publish("b-a", _blocked("U259"))
            box.publish("b-b", _blocked("U251-L1"))
            result = run_sentinel_cycle(root, box)
            self.assertTrue(result["p1_wake_emitted"])
            self.assertEqual([], result["p1_superseded"])

    def test_is_p1_letter_and_card_number_prefix_are_never_cleared(self) -> None:
        # U86 DONE must not clear a letter of card U860; an is_p1 letter always stays.
        schedule = {"updated_at": AFTER_ISO, "phases": [
            {"phase_id": "U86", "state": "DONE", "updated_at": AFTER},
            {"phase_id": "U90", "state": "DONE", "updated_at": AFTER},
        ]}
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, schedule)
            box.publish("b-a", _blocked("U860-L1"))
            box.publish("b-b", _blocked("U90", is_p1=True))
            result = run_sentinel_cycle(root, box)
            self.assertTrue(result["p1_wake_emitted"])
            self.assertEqual([], result["p1_superseded"])

    def test_missing_or_unreadable_schedule_or_letter_time_keeps_the_alert(self) -> None:
        for schedule in (None, "{not json", {"phases": "x"}, {"phases": [{"phase_id": "U169", "state": "DONE"}]}):
            with self.subTest(schedule=schedule), tempfile.TemporaryDirectory() as d:
                root, box = _project(d, schedule)
                box.publish("b-a", _blocked("U169"))
                result = run_sentinel_cycle(root, box)
                self.assertTrue(result["p1_wake_emitted"])
                self.assertEqual([], result["p1_superseded"])
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, {"phases": [{"phase_id": "U169", "state": "DONE", "updated_at": AFTER}]})
            box.publish("b-a", {"kind": "BLOCKED", "step": "U169", "actor": "claude"})  # no letter time
            result = run_sentinel_cycle(root, box)
            self.assertTrue(result["p1_wake_emitted"])


if __name__ == "__main__":
    unittest.main()
