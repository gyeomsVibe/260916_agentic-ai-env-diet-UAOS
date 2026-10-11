"""Judge-owned regression; only disposable test roots are mutated."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, sys.argv.pop(1))
from v7_harness.coord import stall


class SafetyBoundary(unittest.TestCase):
    def test_terminal_state_beats_stale_wait(self):
        phase = {"phase_id": "finished", "state": "DONE", "waiting_on": "claude"}
        self.assertEqual(stall._phase_waits({"phases": [phase]}), [])

    def test_failed_gate_is_not_merge_work(self):
        phase = {"phase_id": "safety", "state": "BLOCKED", "owner_tool": "claude",
                 "waiting_on": "human", "blocker_kind": "SAFETY_GATE",
                 "note": "UAC approved; safety failed; do not merge"}
        self.assertEqual(stall._phase_waits({"phases": [phase]}), [])

    def test_timer_quorum_preserves_scope_boundary(self):
        with tempfile.TemporaryDirectory(prefix="uaos_u184_owned_") as directory:
            root = Path(directory)
            (root / ".coord").mkdir()
            phase = {"phase_id": "scope", "state": "HUMAN", "owner_tool": "claude",
                     "waiting_on": "human", "waiting_since": 1,
                     "blocker_kind": "SCOPE_DECISION",
                     "note": "User scope decision required; no merge authorized"}
            path = root / stall.SCHEDULE
            before = json.dumps({"phases": [phase]}).encode()
            path.write_bytes(before)
            result = stall.scan(root, "codex", now=10000,
                                desk={"codex": {"state": "ACTIVE"}})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result["adopted"], [])


if __name__ == "__main__":
    unittest.main()
