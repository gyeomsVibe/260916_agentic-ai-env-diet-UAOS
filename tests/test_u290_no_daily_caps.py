"""U290: no daily count cap on Antigravity auto-replies (윤겸스 2026-11-01 "모든 한도를 없애라").

Receipt 2026-11-01: an approval request to Antigravity parked as AGY_CAP_REACHED_BACKLOG after 20 answers, and the
U277-A11 card had to be re-routed to another judge. The cap stays available as an opt-in (tests patch it), but the
shipped default is None: no letter waits for the next Seoul day.
"""

from __future__ import annotations

import unittest

from tests.test_u164_agy_backlog import DAY1, Base
from v7_harness.coord import agy_dispatch, wait_reason


class NoDailyCap(Base):
    def setUp(self):
        super().setUp()
        self._cap.stop()  # the shipped default, not the opt-in cap Base installs

    def tearDown(self):
        self._cap.start()  # Base.tearDown stops it again
        super().tearDown()

    def test_default_has_no_cap(self):
        self.assertIsNone(agy_dispatch.DAILY_CAP)

    def test_a_busy_day_still_answers(self):
        self.fill_cap(DAY1, 200)
        row = agy_dispatch.dispatch(self.project, message_id="relay_u290busy0001", actor="claude",
                                    message="ACTIONABLE_DELTA plain", runner=self.runner, now=DAY1)
        self.assertNotEqual("CAP_REACHED_BACKLOG", row["state"])
        self.assertEqual(1, len(self.calls))
        self.assertEqual([], sorted(p.name for p in self.backlog.glob("*.json")) if self.backlog.is_dir() else [])

    def test_backlog_is_ready_on_a_busy_day(self):
        self.backlog.mkdir(parents=True, exist_ok=True)
        (self.backlog / "relay_u290left0001.json").write_text("{}", encoding="utf-8")
        self.fill_cap(DAY1, 200)
        self.assertTrue(agy_dispatch.backlog_ready(self.project, now=DAY1))

    def test_wait_reason_names_no_cap(self):
        self.backlog.mkdir(parents=True, exist_ok=True)
        (self.backlog / "relay_u290left0002.json").write_text("{}", encoding="utf-8")
        text = "\n".join(wait_reason.reasons(self.project, "claude", now=DAY1))
        self.assertNotIn("한도(None", text)
        self.assertNotIn("소진", text)


if __name__ == "__main__":
    unittest.main()
