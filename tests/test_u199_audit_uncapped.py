"""U199: a verdict request (the commit-gate audit) gets its Antigravity answer past the daily cap; ordinary letters
still wait for the next day. Receipt 2026-10-15: U192 and U195 commits stalled behind CAP_REACHED_BACKLOG; 윤겸스
ordered the audit-reply cap lifted for good."""
import inspect
import json
import unittest

from tests.test_u164_agy_backlog import DAY1, Base
from v7_harness.coord import agy_dispatch, deliver


class AuditUncapped(Base):
    def audit(self, message_id: str = "relay_audit199") -> dict:
        return agy_dispatch.dispatch(self.project, message_id=message_id, actor="claude", message="AUDIT REQUEST U199",
                                     runner=self.runner, now=DAY1, audit=True)

    def test_audit_is_answered_when_the_cap_is_spent(self):
        self.fill_cap(DAY1)
        self.assertEqual("ANSWERED", self.audit()["state"])
        self.assertEqual([], self.parked())

    def test_ordinary_letter_still_parks_at_the_cap(self):
        self.fill_cap(DAY1)
        self.assertEqual("CAP_REACHED_BACKLOG", self.park("ACTIONABLE_DELTA plain")["state"])

    def test_audit_does_not_spend_the_ordinary_cap(self):
        self.fill_cap(DAY1, agy_dispatch.DAILY_CAP - 1)
        self.assertEqual("ANSWERED", self.audit()["state"])
        self.assertEqual("ANSWERED", self.park("ACTIONABLE_DELTA plain")["state"])
        rows = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(r.get("state") == "RESERVED" and r.get("audit") is True for r in rows))

    def test_deliver_marks_only_verdict_requests_as_audits(self):
        self.assertIn("audit=verdict_requested is True", inspect.getsource(deliver.deliver))


if __name__ == "__main__":
    unittest.main()
