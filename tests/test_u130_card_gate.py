"""U130: the commit gate refuses new runtime code of a card whose `card audit` lacks Ollama or Antigravity evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import calculator_gate as gate


class CardGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _ledger(self, rows):
        path = self.desk / ".coord" / "usage" / "runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_runtime_prefixes_cover_the_installer(self):
        self.assertEqual(gate.CARD_GATED, ("v7_harness/", "uaos_everywhere/"))

    def test_no_new_code_needs_no_card(self):
        self.assertEqual(gate.card_errors("docs only", [], self.desk, [], branch="main"), [])

    def test_new_code_without_a_card_is_refused(self):
        errors = gate.card_errors("fix: x", ["v7_harness/x.py"], self.desk, [], branch="main")
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("CARD_AUDIT:"))

    def test_card_missing_slots_are_named(self):
        self._ledger([{"work_id": "U900-L1", "worker": "local", "input_tokens": 10}])
        errors = gate.card_errors("fix: x\n\nCard: U900\n", ["uaos_everywhere/y.py"], self.desk, [], branch="main")
        self.assertEqual(len(errors), 1)
        self.assertIn("U900", errors[0])
        self.assertIn("agy", errors[0])

    def test_audited_card_passes_by_branch(self):
        self._ledger([{"work_id": "U900-L1", "worker": "local", "input_tokens": 10},
                      {"work_id": "U900-R1", "worker": "agy", "input_tokens": 10}])
        self.assertEqual(gate.card_errors("fix: x", ["v7_harness/x.py"], self.desk, [],
                                          branch="claude/u900-demo"), [])


if __name__ == "__main__":
    unittest.main()
