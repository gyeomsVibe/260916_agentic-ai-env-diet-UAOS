"""U205: the sentinel wakes the owner of a ready step nobody started (receipt: U196 PENDING 15 h, 2026-10-16)."""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import owner_wake, sentinel
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.stall import MAX_WAIT_S, NOTICE_KEEP_S

NOW = 2_000_000_000.0


class OwnerWake(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.root / ".coord" / "mailbox")

    def tearDown(self):
        self._tmp.cleanup()

    def schedule(self, *phases, written=NOW):
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"phases": list(phases)}), encoding="utf-8")
        os.utime(path, (written, written))

    def wake(self, now):
        return owner_wake.wake_owners(self.root, self.box, now=now)

    def letters(self):
        return [payload for _, payload in self.box.peek()]

    def test_a_ready_step_untouched_past_the_wait_limit_wakes_its_owner(self):
        self.schedule({"phase_id": "D", "state": "DONE"},
                      {"phase_id": "U1", "state": "PENDING", "owner_tool": "claude", "depends_on": ["D"]})
        self.assertEqual([], self.wake(NOW))  # the first scan sees it ready
        self.assertEqual(1, len(self.wake(NOW + MAX_WAIT_S)))
        letter = self.letters()[0]
        self.assertEqual("claude", letter["requested_target"])
        self.assertEqual("ACTIONABLE", letter["wake_class"])
        self.assertIn("U1", letter["delta"])

    def test_a_fresh_step_does_not_wake(self):
        self.schedule({"phase_id": "U1", "state": "READY", "owner_tool": "codex"})
        self.wake(NOW)
        self.assertEqual([], self.wake(NOW + MAX_WAIT_S - 60))

    def test_a_step_with_an_unfinished_dependency_does_not_wake(self):
        self.schedule({"phase_id": "D", "state": "REVIEW"},
                      {"phase_id": "U1", "state": "PENDING", "owner_tool": "claude", "depends_on": ["D"]})
        self.wake(NOW)
        self.assertEqual([], self.wake(NOW + MAX_WAIT_S))

    def test_a_just_finished_dependency_gives_the_full_wait(self):
        self.schedule({"phase_id": "D", "state": "REVIEW"},
                      {"phase_id": "U1", "state": "PENDING", "owner_tool": "claude", "depends_on": ["D"],
                       "updated_at": NOW - 10 * MAX_WAIT_S})
        self.wake(NOW)
        self.schedule({"phase_id": "D", "state": "DONE"},
                      {"phase_id": "U1", "state": "PENDING", "owner_tool": "claude", "depends_on": ["D"],
                       "updated_at": NOW - 10 * MAX_WAIT_S}, written=NOW + MAX_WAIT_S)
        self.assertEqual([], self.wake(NOW + MAX_WAIT_S))
        self.assertEqual(1, len(self.wake(NOW + 2 * MAX_WAIT_S)))

    def test_waiting_human_and_done_states_are_not_woken(self):
        self.schedule(*({"phase_id": s, "state": s, "owner_tool": "claude"} for s in ("REVIEW", "BLOCKED", "HUMAN",
                                                                                    "DONE", "DONE-ACTING")))
        self.assertEqual([], self.wake(NOW + 10 * MAX_WAIT_S))

    def test_an_unrelated_schedule_write_does_not_restart_the_wait_or_repeat_the_wake(self):
        step = {"phase_id": "U1", "state": "REWORK", "owner_tool": "antigravity"}
        self.schedule(step)
        self.wake(NOW)
        self.schedule(step, {"phase_id": "OTHER", "state": "DONE"}, written=NOW + 60)
        self.wake(NOW + 60)
        self.assertEqual(1, len(self.wake(NOW + MAX_WAIT_S)))
        self.schedule(step, {"phase_id": "OTHER2", "state": "DONE"}, written=NOW + MAX_WAIT_S + 30)
        self.assertEqual([], self.wake(NOW + MAX_WAIT_S + 60))

    def test_the_wake_is_sent_once_per_window_and_repeats_after_it(self):
        self.schedule({"phase_id": "U1", "state": "PENDING", "owner_tool": "claude"})
        self.wake(NOW)
        self.assertEqual(1, len(self.wake(NOW + MAX_WAIT_S)))
        self.assertEqual([], self.wake(NOW + MAX_WAIT_S + 60))
        self.assertEqual(1, len(self.wake(NOW + MAX_WAIT_S + NOTICE_KEEP_S)))

    def test_a_missing_or_broken_schedule_sends_nothing(self):
        self.assertEqual([], self.wake(NOW))
        (self.root / ".coord" / "master_schedule.json").write_text("{", encoding="utf-8")
        self.assertEqual([], self.wake(NOW))

    def test_the_sentinel_cycle_runs_the_owner_wake(self):
        source = inspect.getsource(sentinel.run_sentinel_cycle)
        self.assertIn("wake_owners(", source)
        self.assertIn('"owner_wake"', source)


if __name__ == "__main__":
    unittest.main()
