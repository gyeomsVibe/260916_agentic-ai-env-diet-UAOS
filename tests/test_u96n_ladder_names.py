"""U96-N: the handoff ladder says AMPLE/LOW/HANDOFF_READY, and old NORMAL/THRIFT records still read correctly."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import presence
from v7_harness.coord.thrift import AMPLE, HANDOFF_READY, LEGACY_STATES, LOW, apply

FIELDS = dict(current_card="U96-N", next_action="rename", acceptance="python -m unittest", stop_condition="test changed")


class LadderNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord/mailbox").mkdir(parents=True)
        for tool in presence.TOOLS:
            presence.mark(self.root, tool, "ACTIVE")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _old_record(self, state: str) -> None:
        path = self.root / ".coord/thrift/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "uaos-thrift-v1", "sequence": 1,
                                    "tools": {"codex": {"state": state, "input_fingerprint": "pre-u96n"}}}), encoding="utf-8")

    def test_no_state_is_named_normal_or_thrift(self) -> None:
        states = {apply(self.root / str(v), tool="codex", remaining_percent=v, **FIELDS)["state"]
                  for v in (80, 15, 5) if not (self.root / str(v) / ".coord/mailbox").mkdir(parents=True)}
        self.assertEqual({AMPLE, LOW, HANDOFF_READY}, states)
        self.assertFalse(states & {"NORMAL", "THRIFT"})
        self.assertEqual({"NORMAL": AMPLE, "THRIFT": LOW}, LEGACY_STATES)

    def test_old_thrift_record_returns_for_review(self) -> None:
        self._old_record("THRIFT")
        result = apply(self.root, tool="codex", remaining_percent=80)
        self.assertEqual(("ACTIONABLE_DELTA", "RETURN_REVIEW", AMPLE), (result["status"], result["event"], result["state"]))

    def test_old_normal_record_is_not_a_return(self) -> None:
        self._old_record("NORMAL")
        result = apply(self.root, tool="codex", remaining_percent=80)
        self.assertEqual(("ACK_ONLY", "HANDOFF", AMPLE), (result["status"], result["event"], result["state"]))


if __name__ == "__main__":
    unittest.main()
