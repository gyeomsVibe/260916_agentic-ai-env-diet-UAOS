"""U311: a checkout-local obstruction must not stall independent ready work."""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import next_card


class IndependentProgress(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.coord = self.root / ".coord"
        self.coord.mkdir()
        self.other = self.root / "other-checkout"
        self.other.mkdir()

    def phase(self, card, **fields):
        return {"phase_id": card, "state": "READY", "owner_tool": "codex",
                "depends_on": [], **fields}

    def schedule(self, *phases):
        (self.coord / "master_schedule.json").write_text(
            json.dumps({"phases": phases}), encoding="utf-8")

    def claim(self):
        return next_card.next_step(self.root, "codex", claim=True,
                                   session="independent-worker", now=1000.0)

    def assert_claimed_only(self, expected):
        claims = self.coord / "next" / "claims"
        self.assertEqual([expected], sorted(p.stem for p in claims.glob("*.json")))
        held = json.loads((claims / f"{expected}.json").read_text(encoding="utf-8"))
        self.assertEqual("independent-worker", held["session"])

    def test_foreign_checkout_does_not_hide_later_local_card(self):
        self.schedule(self.phase("FOREIGN", worktree=str(self.other)),
                      self.phase("LOCAL", worktree=str(self.root)))
        result = self.claim()
        self.assertEqual(("NEXT", "LOCAL"), (result["state"], result["card"]))
        self.assert_claimed_only("LOCAL")

    def test_foreign_checkout_does_not_hide_later_unbound_card(self):
        self.schedule(self.phase("FOREIGN", worktree=str(self.other)),
                      self.phase("UNBOUND"))
        result = self.claim()
        self.assertEqual(("NEXT", "UNBOUND"), (result["state"], result["card"]))
        self.assert_claimed_only("UNBOUND")

    def test_only_foreign_checkout_preserves_mismatch_diagnostic(self):
        self.schedule(self.phase("FOREIGN", worktree=str(self.other)))
        result = self.claim()
        self.assertEqual(("WAIT", "WORKTREE_MISMATCH", "FOREIGN"),
                         (result["state"], result["code"], result["card"]))
        self.assertFalse((self.coord / "next" / "claims" / "FOREIGN.json").exists())

    def test_unfinished_dependency_is_not_bypassed(self):
        self.schedule(self.phase("LONG", state="ACTIVE", owner_tool="antigravity"),
                      self.phase("DEPENDENT", depends_on=["LONG"]),
                      self.phase("INDEPENDENT", worktree=str(self.root)))
        result = self.claim()
        self.assertEqual(("NEXT", "INDEPENDENT"), (result["state"], result["card"]))
        self.assert_claimed_only("INDEPENDENT")

    def test_live_claim_is_preserved_while_later_card_progresses(self):
        self.schedule(self.phase("HELD"), self.phase("INDEPENDENT"))
        claims = self.coord / "next" / "claims"
        claims.mkdir(parents=True)
        held_path = claims / "HELD.json"
        before = json.dumps({"session": "long-running-worker", "tool": "codex", "at": 999.0})
        held_path.write_text(before, encoding="utf-8")
        result = self.claim()
        self.assertEqual(("NEXT", "INDEPENDENT"), (result["state"], result["card"]))
        self.assertEqual(before, held_path.read_text(encoding="utf-8"))
        self.assertTrue((claims / "INDEPENDENT.json").is_file())


if __name__ == "__main__":
    unittest.main()
