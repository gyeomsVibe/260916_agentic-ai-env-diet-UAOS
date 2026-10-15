"""Maintained independent U197 acceptance; run from the candidate checkout."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_u197_transition_controller as fixture
T0 = fixture.T0
from v7_harness.coord import transition


class IndependentAcceptance(unittest.TestCase):
    def setUp(self):
        self.case = fixture.TransitionTest()
        self.case.setUp()
        self.case._desk()

    def tearDown(self):
        self.case.tearDown()

    def test_native_session_bound_ready_card_is_not_silently_skipped(self):
        self.case._phases([{"phase_id": "U900", "state": "READY", "owner_tool": "claude",
                            "owner_session": "expected-session"}])
        out = self.case._run(T0)
        self.assertEqual(len(out["published"]), 1, out)
        body = self.case._letters()[out["published"][0]]
        self.assertEqual(body["requested_target"], "claude")

    def test_wrong_native_session_claim_does_not_stop_retries(self):
        self.case._run(T0)
        record_path = next((self.case.root / transition.OUTBOX).glob("*.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["owner_session"] = "expected-session"
        claims = self.case.schedule.parent / "next" / "claims"
        claims.mkdir(parents=True)
        (claims / "U900.json").write_text(json.dumps({"tool": "claude", "session": "wrong-session",
                                                       "at": T0 + 5}), encoding="utf-8")
        self.assertFalse(transition._claimed(self.case.root, record))

    def test_failed_publication_recovers_next_cycle_without_burning_attempt(self):
        with patch.object(transition, "_letter", side_effect=OSError("injected publish failure")):
            try:
                self.case._run(T0)
            except OSError:
                pass
        out = self.case._run(T0 + 1)
        self.assertEqual(len(out["published"]), 1, out)
        record = json.loads(next((self.case.root / transition.OUTBOX).glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(record["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
