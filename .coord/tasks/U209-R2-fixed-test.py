"""Frozen reviewer gate: reroute eligibility must preserve explicit conductor stops."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(sys.argv.pop(1)).resolve()))
from v7_harness.coord.stall import _phase_waits


class ProtectedPhaseGate(unittest.TestCase):
    def phase(self, owner="codex", state="BLOCKED", **fields):
        return {"phase_id": "U209-FIXTURE", "owner_tool": owner, "state": state, **fields}

    def test_false_implementation_grant_never_becomes_reroute_work_for_any_tool(self):
        for owner in ("codex", "claude", "antigravity"):
            for state in ("BLOCKED", "REVIEW"):
                with self.subTest(owner=owner, state=state):
                    data = {"phases": [self.phase(owner, state, implementation_go=False)]}
                    before = copy.deepcopy(data)
                    self.assertEqual([], _phase_waits(data))
                    self.assertEqual(before, data)

    def test_explicit_stop_wins_over_a_conflicting_positive_flag(self):
        for owner in ("codex", "claude", "antigravity"):
            with self.subTest(owner=owner):
                data = {"phases": [self.phase(owner, implementation_go=True,
                                            actuator_verdict="STOP_NO_IMPLEMENTATION_GO")]}
                self.assertEqual([], _phase_waits(data))

    def test_unprotected_legacy_and_positive_phases_remain_eligible(self):
        for fields in ({}, {"implementation_go": True}):
            with self.subTest(fields=fields):
                waits = _phase_waits({"phases": [self.phase(**fields)]})
                self.assertEqual(["phase:U209-FIXTURE"], [w["item"] for w in waits])

    def test_existing_safety_gate_and_unrelated_phase_are_preserved(self):
        data = {"phases": [self.phase(blocker_kind="SAFETY_GATE"),
                           {"phase_id": "OTHER", "state": "REVIEW", "owner_tool": "claude"}]}
        before = copy.deepcopy(data)
        self.assertEqual(["phase:OTHER"], [w["item"] for w in _phase_waits(data)])
        self.assertEqual(before, data)


if __name__ == "__main__":
    unittest.main()
