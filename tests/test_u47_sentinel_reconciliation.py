"""U47-P1: SQLite terminal state overrides only stale reconciliation summaries."""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.broker.core import BrokerCore
from v7_harness.coord.sentinel import check_ledger_reconciliation


H = "a" * 64


class SentinelLedgerReconciliationTest(unittest.TestCase):
    def _pilot(self, directory: str, task: str = "T1") -> Path:
        pilot = Path(directory) / "pilot"
        run = pilot / "runs" / task
        run.mkdir(parents=True)
        (run / "summary.json").write_text(
            json.dumps({"state": "FAILED", "error_class": "NEEDS_RECONCILIATION", "effect_state": "UNKNOWN"}),
            encoding="utf-8",
        )
        return pilot

    def _attempt(self, pilot: Path, task: str, state: str) -> None:
        core = BrokerCore(pilot / "coord.sqlite3")
        core.start()
        try:
            core.connection.execute(
                "INSERT INTO plans(task_id,card_revision,status,depends_json,acceptance_hash) VALUES(?,0,'ACTIVE','[]',?)",
                (task, H),
            )
            core.connection.execute(
                "INSERT INTO attempts(attempt_id,task_id,max_hops,state,idempotency_key) VALUES(?,?,1,?,?)",
                (f"{task}-a001", task, state, f"{task}:a001"),
            )
        finally:
            core.close()

    def test_succeeded_attempt_suppresses_stale_failed_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pilot = self._pilot(directory)
            self._attempt(pilot, "T1", "SUCCEEDED")
            self.assertEqual([], check_ledger_reconciliation(pilot))

    def test_nonterminal_attempts_still_require_reconciliation(self) -> None:
        for state in ("RUNNING", "NEEDS_RECONCILIATION"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                pilot = self._pilot(directory)
                self._attempt(pilot, "T1", state)
                self.assertEqual(["T1"], check_ledger_reconciliation(pilot))

    def test_missing_or_invalid_database_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pilot = self._pilot(directory)
            self.assertEqual(["T1"], check_ledger_reconciliation(pilot))
            (pilot / "coord.sqlite3").write_bytes(b"not sqlite")
            self.assertEqual(["T1"], check_ledger_reconciliation(pilot))

    def test_summary_only_fixture_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pilot = self._pilot(directory, "legacy")
            self.assertEqual(["legacy"], check_ledger_reconciliation(pilot))


if __name__ == "__main__":
    unittest.main()
