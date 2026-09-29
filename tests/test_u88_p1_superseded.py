"""U88: a BLOCKED message whose step later passed (itself or its -R<n> retry) no longer raises the P1 wake.

Seen 2026-09-29: the sentinel's P1 wake listed U80 and U86 after U80-R1 and U86-R1 had passed, and it grew with every
BLOCKED message ever sent, so the single P1 shown at every session start carried no signal. The ledger PASS row, later
than the message, is the evidence; anything unproven keeps its alert.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

BLOCKED_AT = "2026-09-29T11:44:32+09:00"
BEFORE = datetime.fromisoformat(BLOCKED_AT).timestamp() - 60
AFTER = datetime.fromisoformat(BLOCKED_AT).timestamp() + 60


def _project(directory: str, rows: list[dict]) -> tuple[Path, Mailbox]:
    root = Path(directory)
    (root / ".coord" / "mailbox").mkdir(parents=True)
    ledger = root / ".coord" / "usage" / "runs.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return root, Mailbox(root / ".coord" / "mailbox")


def _pass(work_id: str, ts: float) -> dict:
    return {"kind": "pilot", "work_id": work_id, "outcome": "PASS", "worker": "apply", "ts": ts}


def _blocked(step: str) -> dict:
    return {"kind": "BLOCKED", "step": step, "ts": BLOCKED_AT, "actor": "claude"}


class SupersededBlockTests(unittest.TestCase):
    def test_a_passed_retry_clears_the_block(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86-R1", AFTER), _pass("U80", AFTER)])
            box.publish("b86", _blocked("U86"))
            box.publish("b80", _blocked("U80"))
            result = run_sentinel_cycle(root, box)
            self.assertFalse(result["p1_wake_emitted"])
            self.assertEqual(["U80", "U86"], result["p1_superseded"])

    def test_a_pass_before_the_block_or_of_another_step_keeps_the_alert(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86", BEFORE), _pass("U860-R1", AFTER), _pass("U86-F1", AFTER)])
            box.publish("b86", _blocked("U86"))
            result = run_sentinel_cycle(root, box)
            self.assertTrue(result["p1_wake_emitted"])
            self.assertEqual([], result["p1_superseded"])

    def test_a_block_without_a_readable_time_keeps_the_alert(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86", AFTER)])
            box.publish("b86", {"kind": "BLOCKED", "step": "U86", "ts": "yesterday"})
            self.assertTrue(run_sentinel_cycle(root, box)["p1_wake_emitted"])

    def test_an_explicit_p1_is_never_cleared_by_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U86", AFTER)])
            box.publish("p86", {"kind": "NOTE", "is_p1": True, "step": "U86", "ts": BLOCKED_AT})
            self.assertTrue(run_sentinel_cycle(root, box)["p1_wake_emitted"])


if __name__ == "__main__":
    unittest.main()
