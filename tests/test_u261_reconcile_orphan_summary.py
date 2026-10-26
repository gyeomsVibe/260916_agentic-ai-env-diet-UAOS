"""U261: `pilot reconcile` also clears a failed run summary whose ledger holds no open attempt.

Seen 2026-10-27: every one of 10 P1 wakes began with `NEEDS_RECONCILIATION: U243-L1`. Its summary is FAILED /
SOURCE_DIVERGED / effect UNKNOWN (the run was refused before any attempt row was written), so the sentinel asks for
`pilot reconcile`, and reconcile answered NOTHING_TO_RECONCILE because it only looked for open attempts - the alert
could never clear. Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.broker.core import BrokerCore
from v7_harness.coord.sentinel import check_ledger_reconciliation
from v7_harness.pilot import reconcile_pilot

ORPHAN = {"state": "FAILED", "error_class": "SOURCE_DIVERGED", "effect_state": "UNKNOWN", "promotion": "BLOCKED",
          "verdict_hint": "BLOCKED", "changed_files": [], "bundle_id": None}


def _work_dir(directory: str, summary: dict, *, with_db: bool = True) -> Path:
    work = Path(directory)
    if with_db:
        core = BrokerCore(work / "coord.sqlite3")
        core.start()
        core.close()
    run = work / "runs" / "U9-L1"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return work


class ReconcileOrphanSummaryTests(unittest.TestCase):
    def test_orphan_failed_summary_is_abandoned_and_the_alert_clears(self) -> None:
        for with_db in (True, False):
            with self.subTest(with_db=with_db), tempfile.TemporaryDirectory() as d:
                work = _work_dir(d, ORPHAN, with_db=with_db)
                self.assertEqual(["U9-L1"], check_ledger_reconciliation(work))
                result = reconcile_pilot(work_dir=work, task_id="U9-L1")
                self.assertEqual({"state": "ABANDONED", "reconciled_attempts": 0}, result)
                summary = json.loads((work / "runs" / "U9-L1" / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual("ABANDONED", summary["state"])
                self.assertEqual("SOURCE_DIVERGED", summary.get("abandoned_from_error_class"))
                self.assertEqual([], check_ledger_reconciliation(work))

    def test_summary_that_needs_nothing_is_left_untouched(self) -> None:
        for summary in ({"state": "SUCCEEDED", "error_class": "NONE", "effect_state": "CONFIRMED"},
                        {"state": "FAILED", "error_class": "CODE", "effect_state": "NONE"}):
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as d:
                work = _work_dir(d, summary)
                path = work / "runs" / "U9-L1" / "summary.json"
                before = path.read_bytes()
                result = reconcile_pilot(work_dir=work, task_id="U9-L1")
                self.assertEqual({"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0}, result)
                self.assertEqual(before, path.read_bytes())

    def test_missing_task_or_unreadable_summary_is_nothing_to_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            work = _work_dir(d, ORPHAN)
            self.assertEqual({"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0},
                             reconcile_pilot(work_dir=work, task_id="U9-NONE"))
            (work / "runs" / "U9-L1" / "summary.json").write_text("{bad", encoding="utf-8")
            self.assertEqual({"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0},
                             reconcile_pilot(work_dir=work, task_id="U9-L1"))


if __name__ == "__main__":
    unittest.main()
