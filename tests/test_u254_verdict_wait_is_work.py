"""U254 fixed acceptance: a verdict owed by a tool is that tool's next step, and closed states are not open work.

Receipt (2026-10-26): `coord next --tool claude` said WAIT over 11 "open" cards while U253 sat in REVIEW with
`waiting_on: claude-verdict`. Ten of the cards were DONE_SCOPED/RETIRED/DONE_ELSEWHERE/SUPERSEDED, and the one real
item, claude's verdict, was nobody's NEXT, so the stop gate let every tool end its turn and all three idled.
"""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import next_card as N


def phase(pid, state, owner="claude", deps=(), **extra):
    return {"phase_id": pid, "state": state, "owner_tool": owner, "depends_on": list(deps), **extra}


class VerdictWaitIsWork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, *phases):
        (self.root / ".coord" / "master_schedule.json").write_text(
            json.dumps({"schedule_id": "T", "phases": list(phases)}), encoding="utf-8")

    def test_review_waiting_on_my_verdict_is_my_next(self):
        self.schedule(phase("U253", "REVIEW", owner="antigravity", waiting_on="claude-verdict"))
        out = N.next_step(self.root, "claude")
        self.assertEqual(("NEXT", "U253", "VERDICT"), (out["state"], out["card"], out.get("kind")))

    def test_reviewer_field_names_the_verdict_owner(self):
        self.schedule(phase("X", "REVIEW", owner="claude", reviewer="antigravity"))
        self.assertEqual("NEXT", N.next_step(self.root, "antigravity")["state"])
        self.assertNotEqual("NEXT", N.next_step(self.root, "claude")["state"])  # the author never judges itself

    def test_verdict_owed_by_another_tool_is_not_mine(self):
        self.schedule(phase("U253", "REVIEW", owner="antigravity", waiting_on="codex-verdict"))
        self.assertNotEqual("NEXT", N.next_step(self.root, "claude")["state"])

    def test_own_ready_card_still_comes_first(self):
        self.schedule(phase("A", "READY"), phase("R", "REVIEW", owner="antigravity", waiting_on="claude-verdict"))
        self.assertEqual("A", N.next_step(self.root, "claude")["card"])

    # Codex R4 counterexamples (relay_4aebffa4, frozen gate round4/test_u254_external.py).
    def test_author_never_judges_even_when_named_reviewer(self):
        self.schedule(phase("X", "REVIEW", owner="antigravity", author_tool="claude", reviewer="claude"))
        self.assertNotEqual("VERDICT", N.next_step(self.root, "claude").get("kind"))

    def test_reviewer_wins_over_waiting_on(self):
        self.schedule(phase("X", "REVIEW", owner="antigravity", reviewer="claude", waiting_on="codex-verdict"))
        kinds = [N.next_step(self.root, t).get("kind") for t in ("claude", "codex")]
        self.assertEqual(["VERDICT", None], kinds)

    def test_one_session_claims_a_verdict(self):
        self.schedule(phase("X", "REVIEW", owner="antigravity", reviewer="claude"))
        got = [N.next_step(self.root, "claude", claim=True, session=s).get("kind") for s in ("one", "two")]
        self.assertEqual(1, got.count("VERDICT"))

    def test_closed_states_are_not_open_work(self):
        self.schedule(*[phase(s, s) for s in ("DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED", "SUPERSEDED", "DONE")])
        self.assertEqual("DONE", N.next_step(self.root, "claude")["state"])


if __name__ == "__main__":
    unittest.main()
