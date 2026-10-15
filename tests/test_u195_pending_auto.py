"""Maintained U195 black-box acceptance, frozen before implementation."""
import json
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
from v7_harness.coord import next_card as N
from v7_harness.coord.stream import _exclusive


def _mutate(path, field, ready, done):
    path = Path(path)
    if not ready.wait(10):
        raise RuntimeError("candidate was never offered")
    locks = path.parent / "next" / "claims"
    locks.mkdir(parents=True, exist_ok=True)
    with _exclusive(locks / ".lock"):
        data = json.loads(path.read_text())
        if field == "flag":
            data["phases"][1]["auto_promote"] = False
        elif field == "dependency":
            data["phases"][0]["state"] = "REVIEW"
        else:
            data["phases"][1]["caps"] = {"tokens": {"used": 10, "limit": 10}}
        path.write_text(json.dumps(data), encoding="utf-8")
    done.set()


class PendingAuto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="u195_")
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()
        self.path = self.root / ".coord/master_schedule.json"

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, changes=None, *, owner="codex", parent="DONE", deps=None):
        child = {"phase_id": "B", "state": "PENDING", "auto_promote": True,
                 "owner_tool": owner, "depends_on": ["A"] if deps is None else deps}
        child.update(changes or {})
        rows = [{"phase_id": "A", "state": parent, "owner_tool": owner}, child]
        self.path.write_text(json.dumps({"phases": rows}), encoding="utf-8")
        return self.path.read_bytes()

    def blocked(self, **changes):
        before = self.schedule(changes)
        self.assertEqual("WAIT", N.next_step(self.root, "codex")["state"])
        self.assertEqual(before, self.path.read_bytes())

    def test_all_three_tools_opt_in_without_writing_schedule(self):
        for tool in ("codex", "claude", "antigravity"):
            with self.subTest(tool=tool):
                before = self.schedule(owner=tool)
                out = N.next_step(self.root, tool, session="native-" + tool)
                self.assertEqual(("NEXT", "B"), (out["state"], out.get("card")))
                self.assertEqual(before, self.path.read_bytes())

    def test_flag_requires_boolean_true(self):
        for value in (None, False, 0, 1, "true", [], {}):
            with self.subTest(value=value):
                self.blocked(auto_promote=value)
        self.schedule()
        data = json.loads(self.path.read_text())
        del data["phases"][1]["auto_promote"]
        self.path.write_text(json.dumps(data))
        self.assertEqual("WAIT", N.next_step(self.root, "codex")["state"])

    def test_human_and_failed_gate_presence_is_protected(self):
        for key in ("human", "gate_failed"):
            for value in (False, None, "", {}, True):
                with self.subTest(key=key, value=value):
                    self.blocked(**{key: value})

    def test_only_done_dependencies_satisfy_automatic_path(self):
        for state in ("REVIEW", "FAILED", "BLOCKED", "ACTIVE", "HUMAN", "REWORK"):
            with self.subTest(state=state):
                self.schedule(parent=state)
                self.assertEqual("WAIT", N.next_step(self.root, "codex")["state"])

    def test_malformed_and_missing_dependencies_are_not_candidates(self):
        for deps in (["missing"], ["A", "A"], [1], [""], "A", 7):
            with self.subTest(deps=deps):
                self.schedule(deps=deps)
                self.assertEqual("WAIT", N.next_step(self.root, "codex")["state"])
        self.blocked(depends_on=None)

    def test_explicit_empty_dependencies_can_start_first_phase(self):
        self.schedule(deps=[])
        self.assertEqual("NEXT", N.next_step(self.root, "codex")["state"])

    def test_duplicate_or_malformed_phase_ids_fail_closed(self):
        for value in (None, "", 1, "A"):
            with self.subTest(value=value):
                self.schedule({"phase_id": value})
                self.assertEqual("WAIT", N.next_step(self.root, "codex")["state"])

    def test_rerouted_protected_or_malformed_metadata_blocks(self):
        for state in ("HUMAN", "PARKED", "SCOPE", "BLOCKED", "REWORK", "FAILED"):
            with self.subTest(state=state):
                self.blocked(rerouted_from={"state": state})
        for value in (None, True, [], "HUMAN"):
            self.blocked(rerouted_from=value)

    def test_finite_nonexhausted_caps_are_candidates(self):
        for cap in ({"used": 0, "limit": 10}, {"used": .25, "limit": 1.5},
                    {"used": 0, "limit": 10 ** 400}):
            with self.subTest(cap=cap):
                self.schedule({"caps": {"tokens": cap}})
                self.assertEqual("NEXT", N.next_step(self.root, "codex")["state"])

    def test_invalid_and_exhausted_caps_fail_closed(self):
        caps = [None, [], {"t": {}}, {"t": {"used": True, "limit": 10}},
                {"t": {"used": 0, "limit": True}}, {"t": {"used": -1, "limit": 10}},
                {"t": {"used": 10, "limit": 10}}, {"t": {"used": 0, "limit": 0}},
                {"t": {"used": "0", "limit": 10}}, {"t": {"used": 0, "limit": float("inf")}},
                {"t": {"used": float("nan"), "limit": 10}},
                {"t": {"used": 0, "limit": 10, "remaining": 10}}]
        for value in caps:
            with self.subTest(value=value):
                self.blocked(caps=value)

    def test_unknown_resource_fields_are_not_guessed(self):
        for key in ("token_cap", "budget_limit", "max_tokens", "quota", "attempt_cap", "remaining"):
            with self.subTest(key=key):
                self.blocked(**{key: 100})

    def test_owner_session_match_and_single_claim_for_three_tools(self):
        for tool in ("codex", "claude", "antigravity"):
            session = "native-" + tool
            self.schedule({"owner_session": session}, owner=tool)
            self.assertEqual("WAIT", N.next_step(self.root, tool, session="wrong")["state"])
            out = N.next_step(self.root, tool, claim=True, session=session, now=100)
            self.assertEqual("NEXT", out["state"])
            held = json.loads((self.path.parent / "next/claims/B.json").read_text())
            self.assertEqual((tool, session), (held["tool"], held["session"]))
            (self.path.parent / "next/claims/B.json").unlink()

    def test_ready_review_stacking_semantics_remain_unchanged(self):
        self.schedule({"state": "READY", "auto_promote": False}, parent="REVIEW")
        self.assertEqual("NEXT", N.next_step(self.root, "codex")["state"])

    def race(self, field):
        self.schedule({"caps": {"tokens": {"used": 0, "limit": 10}}})
        ctx = mp.get_context("spawn")
        ready, done = ctx.Event(), ctx.Event()
        proc = ctx.Process(target=_mutate, args=(str(self.path), field, ready, done))
        original, after = N._claim, []
        def hook(*args, **kwargs):
            ready.set()
            self.assertTrue(done.wait(10), "parallel mutator did not finish")
            after.append(self.path.read_bytes())
            return original(*args, **kwargs)
        proc.start()
        try:
            with patch.object(N, "_claim", side_effect=hook):
                out = N.next_step(self.root, "codex", claim=True, session="native", now=100)
            self.assertTrue(ready.is_set(), "automatic phase was never offered")
            proc.join(10)
            self.assertEqual(0, proc.exitcode)
            self.assertEqual("WAIT", out["state"])
            self.assertEqual(after[0], self.path.read_bytes())
            self.assertFalse((self.path.parent / "next/claims/B.json").exists())
        finally:
            if proc.is_alive():
                proc.terminate()
            proc.join(5)

    def test_parallel_flag_revocation_rejects_claim(self):
        self.race("flag")

    def test_parallel_dependency_regression_rejects_claim(self):
        self.race("dependency")

    def test_parallel_cap_exhaustion_rejects_claim(self):
        self.race("cap")


if __name__ == "__main__":
    unittest.main()
