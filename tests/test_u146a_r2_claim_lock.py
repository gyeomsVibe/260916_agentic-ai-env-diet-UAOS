"""U146a-R2: claim exclusivity under real parallel processes, frozen before the fix (Codex U146-R4 REWORK).

Codex counterexample: two sessions read one expired claim, each atomically replaces it and re-reads its own record, so
both return True; atomic replace plus re-read confers no exclusivity. A creator that has opened the claim file but not
yet written it made a second claimer's os.replace raise an uncaught Windows PermissionError.
Every claimer here is its own interpreter started on one shared go-signal, like simultaneous Stop hooks.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import next_card as N

REPO = Path(__file__).resolve().parents[1]
# 8 claimers: more than the 3 tools x 2 sessions that can meet on one card, so a lost race is likely to show.
CLAIMERS = 8
CLAIMER = ("import json,os,sys,time; from pathlib import Path; from v7_harness.coord import next_card as N; "
           "root, session, go, ready = sys.argv[1:5]; Path(ready).write_text('1'); "
           "deadline = time.time() + 60\n"
           "while not os.path.exists(go) and time.time() < deadline: time.sleep(0.001)\n"
           "print(json.dumps(N.next_step(Path(root), 'claude', claim=True, session=session)))")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()
        (self.root / ".coord" / "master_schedule.json").write_text(
            json.dumps({"phases": [{"phase_id": "A", "state": "READY", "owner_tool": "claude", "depends_on": []}]}),
            encoding="utf-8")
        self.claims = self.root / ".coord" / "next" / "claims"

    def race(self) -> list[dict]:
        go = self.root / "go"
        procs, ready = [], []
        for i in range(CLAIMERS):
            flag = self.root / f"ready{i}"
            ready.append(flag)
            procs.append(subprocess.Popen([sys.executable, "-c", CLAIMER, str(self.root), f"p{i}", str(go), str(flag)],
                                          cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        deadline = time.time() + 60
        while not all(f.exists() for f in ready) and time.time() < deadline:
            time.sleep(0.01)
        go.write_text("1")
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            self.assertEqual(0, proc.returncode, err)
            results.append(json.loads(out))
        return results

    def winners(self, results: list[dict]) -> list[dict]:
        return [r for r in results if r.get("state") == "NEXT" and r.get("claimed")]


class ParallelClaims(Base):
    def test_parallel_fresh_claim_has_exactly_one_winner(self):
        results = self.race()
        self.assertEqual(1, len(self.winners(results)), results)
        holder = json.loads((self.claims / "A.json").read_text(encoding="utf-8"))["session"]
        self.assertEqual(1, sum(1 for r in results if r.get("state") == "NEXT"))
        self.assertIn(holder, {f"p{i}" for i in range(CLAIMERS)})

    def test_parallel_expired_takeover_has_exactly_one_winner(self):
        self.claims.mkdir(parents=True)
        (self.claims / "A.json").write_text(json.dumps({"session": "gone", "tool": "claude", "at": 0}), encoding="utf-8")
        results = self.race()
        self.assertEqual(1, len(self.winners(results)), results)
        self.assertNotEqual("gone", json.loads((self.claims / "A.json").read_text(encoding="utf-8"))["session"])

    def test_losers_wait_and_never_crash(self):
        results = self.race()
        self.assertEqual(CLAIMERS - 1, sum(1 for r in results if r.get("state") == "WAIT"), results)


class PartialCreator(Base):
    def test_claim_file_held_open_by_its_creator_never_raises(self):
        self.claims.mkdir(parents=True)
        handle = open(self.claims / "A.json", "w", encoding="utf-8")  # a creator that opened but has not written
        try:
            step = N.next_step(self.root, "claude", claim=True, session="s2")
            self.assertIn(step["state"], ("NEXT", "WAIT"))
        finally:
            handle.close()
        again = N.next_step(self.root, "claude", claim=True, session="s2")
        self.assertEqual(("NEXT", "A"), (again["state"], again.get("card")))
        self.assertEqual("s2", json.loads((self.claims / "A.json").read_text(encoding="utf-8"))["session"])

    def test_truncated_claim_record_is_taken_over(self):
        self.claims.mkdir(parents=True)
        (self.claims / "A.json").write_text('{"session": "s1", "at"', encoding="utf-8")  # creator died mid-write
        step = N.next_step(self.root, "claude", claim=True, session="s2")
        self.assertEqual(("NEXT", "A"), (step["state"], step.get("card")))

    def test_no_temp_file_is_left_behind(self):
        N.next_step(self.root, "claude", claim=True, session="s1")
        N.next_step(self.root, "claude", claim=True, session="s1")
        self.assertEqual([], sorted(p.name for p in self.claims.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
