"""Additional independent refusal counterexamples; original five remain byte-frozen."""
import contextlib
import json
import unittest
from unittest.mock import patch
import U185_session_accept as gate


class AdditionalAssignment(gate.AssignedSession):
    def test_invalid_explicit_assignments_are_not_unassigned(self):
        for bad in (None, "", 7, []):
            with self.subTest(assigned=bad):
                self.write([{**self.card, "owner_session": bad}])
                result = gate.mod.next_step(self.root, "claude", claim=True, session="writer")
                self.assertNotEqual(result.get("state"), "NEXT", result)
                self.assertFalse(self.claim_file().exists())

    def test_locked_schedule_corruption_or_target_change_refuses(self):
        import v7_harness.coord.stream as stream
        original = stream._exclusive
        for after in ({"phases": None}, {"phases": []}, {"phases": [self.card, self.card]},
                      {"phases": [{**self.card, "state": "HUMAN"}]},
                      {"phases": [{**self.card, "owner_tool": "codex"}]}, None):
            with self.subTest(after=after):
                self.write([self.card])

                @contextlib.contextmanager
                def changed(*args, **kwargs):
                    with original(*args, **kwargs):
                        self.schedule.write_text(json.dumps(after), encoding="utf-8")
                        yield

                with patch.object(stream, "_exclusive", changed):
                    result = gate.mod.next_step(self.root, "claude", claim=True, session="writer")
                self.assertNotEqual(result.get("state"), "NEXT", result)
                self.assertFalse(self.claim_file().exists())

    def test_existing_live_holder_is_not_overwritten(self):
        self.claim_file().parent.mkdir(parents=True, exist_ok=True)
        held = {"session": "existing", "tool": "claude", "at": 100}
        self.claim_file().write_text(json.dumps(held), encoding="utf-8")
        result = gate.mod.next_step(self.root, "claude", claim=True, session="writer", now=101)
        self.assertNotEqual(result.get("state"), "NEXT", result)
        self.assertEqual(json.loads(self.claim_file().read_text()), held)


if __name__ == "__main__":
    unittest.main()
