"""Frozen assignment refusal tests; disposable schedules only, not native authentication."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

source = Path(sys.argv.pop(1))
runtime = Path(sys.argv.pop(1))
sys.path.insert(0, str(runtime))
loader = importlib.util.spec_from_file_location("assigned_next_card", source)
mod = importlib.util.module_from_spec(loader)
loader.loader.exec_module(mod)


class AssignedSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()
        self.schedule = self.root / ".coord/master_schedule.json"
        self.card = {"phase_id": "PINNED", "state": "READY", "owner_tool": "claude",
                     "owner_session": "writer", "depends_on": []}
        self.write([self.card])

    def write(self, phases):
        self.schedule.write_text(json.dumps({"phases": phases}), encoding="utf-8")

    def claim_file(self):
        return self.root / ".coord/next/claims/PINNED.json"

    def test_wrong_session_cannot_execute_or_claim(self):
        for claim in (False, True):
            result = mod.next_step(self.root, "claude", claim=claim, session="other")
            self.assertNotEqual(result.get("state"), "NEXT", result)
        self.assertFalse(self.claim_file().exists())

    def test_missing_session_cannot_execute_assigned_card(self):
        self.assertNotEqual(mod.next_step(self.root, "claude").get("state"), "NEXT")

    def test_matching_session_can_claim(self):
        result = mod.next_step(self.root, "claude", claim=True, session="writer")
        self.assertEqual(result.get("state"), "NEXT", result)
        self.assertEqual(json.loads(self.claim_file().read_text())["session"], "writer")

    def test_other_safe_ready_card_is_not_stranded(self):
        self.write([self.card, {"phase_id": "OTHER", "state": "READY",
                              "owner_tool": "claude", "depends_on": []}])
        result = mod.next_step(self.root, "claude", claim=True, session="other")
        self.assertEqual(result.get("card"), "OTHER", result)
        self.assertFalse(self.claim_file().exists())

    def test_assignment_changed_before_claim_lock_is_refused(self):
        import v7_harness.coord.stream as stream
        original = stream._exclusive

        @contextlib.contextmanager
        def changed_assignment(*args, **kwargs):
            with original(*args, **kwargs):
                self.write([{**self.card, "owner_session": "new-writer"}])
                yield

        with patch.object(stream, "_exclusive", changed_assignment):
            result = mod.next_step(self.root, "claude", claim=True, session="writer")
        self.assertNotEqual(result.get("state"), "NEXT", result)
        self.assertFalse(self.claim_file().exists())


if __name__ == "__main__":
    unittest.main()
