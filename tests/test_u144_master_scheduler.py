"""Unit tests for MasterTaskScheduler (U144)."""

import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.master_scheduler import MasterTaskScheduler


class MasterTaskSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scheduler = MasterTaskScheduler(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_default_schedule(self) -> None:
        sched = self.scheduler.init_default_schedule("TEST-SCHED", "Test Pipeline")
        self.assertEqual(sched.schedule_id, "TEST-SCHED")
        self.assertEqual(len(sched.phases), 5)
        self.assertEqual(sched.current_phase_id, "P1-COMMS")
        self.assertEqual(sched.phases[0].state, "ACTIVE")

    def test_advance_phase_unlocks_dependent(self) -> None:
        self.scheduler.init_default_schedule()
        # P1-COMMS 완료 -> P2-UI-PRIORITY 또는 P3가 활성화되어야 함
        next_p = self.scheduler.advance_phase("P1-COMMS", evidence={"test_exit": 0})
        self.assertIsNotNone(next_p)
        self.assertIn(next_p.phase_id, ("P2-UI-PRIORITY", "P3-MIA-STANDARDIZATION"))
        self.assertEqual(next_p.state, "ACTIVE")

    def test_mark_blocked_records_reason(self) -> None:
        self.scheduler.init_default_schedule()
        self.scheduler.mark_blocked("P1-COMMS", "Evidence missing: pilot bundle")
        loaded = self.scheduler.load_schedule()
        self.assertIsNotNone(loaded)
        p1 = [p for p in loaded.phases if p.phase_id == "P1-COMMS"][0]
        self.assertEqual(p1.state, "BLOCKED")
        self.assertIn("Evidence missing", p1.blocker_reason)

    def test_summary_report(self) -> None:
        self.scheduler.init_default_schedule()
        report = self.scheduler.get_summary_report()
        self.assertEqual(report["schedule_id"], "U144-MASTER")
        self.assertEqual(len(report["phases"]), 5)


if __name__ == "__main__":
    unittest.main()
