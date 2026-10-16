"""U196-REROUTE-BINDING: a phase that names a worktree is claimable only from that existing checkout.

Receipt: Codex REVISE relay_189466e7 / .coord/reviews/U196-installed-worktree-counterexample-20261016.json. A matching
session got NEXT/claimed=True although phase.worktree pointed at a different, nonexistent checkout (all three tools).
The first test mirrors Codex's frozen judge test (SHA 9e71941a) against the source tree instead of the installed runtime.
"""

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.next_card import next_step

TOOLS = ("codex", "claude", "antigravity")


class WorktreeBinding(unittest.TestCase):
    def _schedule(self, root: Path, tool: str, **extra) -> dict:
        phase = dict(phase_id="U196", state="READY", owner_tool=tool, owner_session="assigned", depends_on=[], **extra)
        (root / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": [phase]}), encoding="utf-8")
        return phase

    def _root(self, temp: str) -> Path:
        root = Path(temp)
        (root / ".coord").mkdir()
        return root

    def test_wrong_worktree_cannot_claim_assigned_step(self):
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temp:
                root = self._root(temp)
                self._schedule(root, tool, worktree=str(root))
                self.assertEqual("NEXT", next_step(root, tool, session="assigned")["state"])
                self._schedule(root, tool, worktree=str(root / "different-checkout"))
                got = next_step(root, tool, claim=True, session="assigned")
                self.assertNotEqual("NEXT", got.get("state"), got)
                self.assertEqual("WORKTREE_MISMATCH", got.get("code"), got)

    def test_matching_worktree_claims(self):
        for tool in TOOLS:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as temp:
                root = self._root(temp)
                self._schedule(root, tool, worktree=str(root))
                got = next_step(root, tool, claim=True, session="assigned")
                self.assertEqual(("NEXT", True), (got.get("state"), got.get("claimed")), got)

    def test_existing_other_checkout_cannot_claim(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = self._root(temp)
            self._schedule(root, "claude", worktree=other)
            got = next_step(root, "claude", claim=True, session="assigned")
            self.assertNotEqual("NEXT", got.get("state"), got)

    def test_malformed_worktree_fails_closed(self):
        for bad in ("", None, 7, ["x"]):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temp:
                root = self._root(temp)
                self._schedule(root, "claude", worktree=bad)
                got = next_step(root, "claude", claim=True, session="assigned")
                self.assertNotEqual("NEXT", got.get("state"), got)

    def test_phase_without_worktree_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._schedule(root, "claude")
            got = next_step(root, "claude", claim=True, session="assigned")
            self.assertEqual(("NEXT", True), (got.get("state"), got.get("claimed")), got)

    def test_mismatch_writes_no_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._schedule(root, "claude", worktree=str(root / "gone"))
            next_step(root, "claude", claim=True, session="assigned")
            self.assertFalse((root / ".coord" / "next" / "claims" / "U196.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
