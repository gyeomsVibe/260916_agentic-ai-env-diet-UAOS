"""U290D: the real pre-existing backlog drains under the uncapped default, and the kept safety limits stay.

Codex REVISE relay_b5d48223 (d)+(e): letters parked by the old 20-answer cap (the 29 parked on 2026-11-01) must be
answered on the same day once the default has no cap, and only the two count quotas go; the technical limits remain.
"""

from __future__ import annotations

import json
import unittest

from tests.test_u164_agy_backlog import DAY1, Base
from v7_harness.coord import agy_dispatch, notify


class ParkedBacklogDrains(Base):
    PARKED = 25  # more than the old cap of 20, so a capped drain could not clear it in one day

    def _park_under_cap(self) -> list[str]:
        """Park letters exactly as the old cap did: a full day's ledger, then real dispatch parks each letter."""
        self.fill_cap(DAY1)
        for number in range(self.PARKED):
            row = agy_dispatch.dispatch(self.project, message_id=f"relay_u290dleft{number:04d}", actor="claude",
                                        message=f"ACTIONABLE_DELTA audit parked {number}", runner=self.runner,
                                        now=DAY1, card="U290D")
            self.assertEqual("CAP_REACHED_BACKLOG", row["state"])
        self.assertEqual([], self.calls)
        return self.parked()

    def test_parked_letters_drain_the_same_day_once_the_cap_is_gone(self):
        before = self._park_under_cap()
        self.assertEqual(self.PARKED, len(before))
        self._cap.stop()  # the shipped default: DAILY_CAP is None
        try:
            self.assertIsNone(agy_dispatch.DAILY_CAP)
            self.assertTrue(agy_dispatch.backlog_ready(self.project, now=DAY1 + 60))
            rows = agy_dispatch.drain_backlog(self.project, now=DAY1 + 60, runner=self.runner)
        finally:
            self._cap.start()
        self.assertEqual(["ANSWERED"] * self.PARKED, [row["state"] for row in rows])
        self.assertEqual(self.PARKED, len(self.calls))
        self.assertEqual([], self.parked())
        answered = {json.loads(line).get("message_id") for line in self.ledger.read_text(encoding="utf-8").splitlines()
                    if json.loads(line).get("state") == "ANSWERED"}
        self.assertTrue({f"relay_u290dleft{n:04d}" for n in range(self.PARKED)} <= answered)

    def test_a_second_drain_answers_nothing_twice(self):
        self._park_under_cap()
        self._cap.stop()
        try:
            agy_dispatch.drain_backlog(self.project, now=DAY1 + 60, runner=self.runner)
            calls = len(self.calls)
            again = agy_dispatch.drain_backlog(self.project, now=DAY1 + 120, runner=self.runner)
        finally:
            self._cap.start()
        self.assertEqual([], again)
        self.assertEqual(calls, len(self.calls))


class KeptSafetyLimits(unittest.TestCase):
    """Only the two daily count quotas are removed; every other limit named in the U290 manual still exists."""

    def test_the_two_quotas_default_to_none(self):
        self.assertIsNone(agy_dispatch.DAILY_CAP)
        self.assertIsNone(notify.DAILY_LIMIT)

    def test_technical_and_safety_limits_remain(self):
        self.assertEqual(3, agy_dispatch.BACKLOG_TRIES)
        self.assertGreaterEqual(notify.MIN_INTERVAL.total_seconds(), 60)
        self.assertTrue(hasattr(agy_dispatch, "_budget_lock"))
        self.assertTrue(hasattr(agy_dispatch, "MAX_REPLY_CHARS"))


if __name__ == "__main__":
    unittest.main()
