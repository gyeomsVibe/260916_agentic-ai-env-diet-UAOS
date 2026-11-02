"""U295: branch lease (B2), verdict freeze (B4), full head in verdicts (B3), schedule close and wake reroute (B8)."""

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v7_harness.coord import branch_guard, merge_route, owner_wake, requests  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _repo(tmp: Path) -> tuple[str, str]:
    """A repo whose branch `agy/u1-x` is pushed at c1 and has a local commit c2 on top."""
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@example.invalid")
    _git(tmp, "config", "user.name", "t")
    _git(tmp, "checkout", "-q", "-b", "agy/u1-x")
    (tmp / "a.txt").write_text("1", encoding="utf-8")
    _git(tmp, "add", "a.txt")
    _git(tmp, "commit", "-q", "-m", "c1")
    c1 = _git(tmp, "rev-parse", "HEAD")
    _git(tmp, "update-ref", "refs/remotes/origin/agy/u1-x", c1)
    (tmp / "a.txt").write_text("2", encoding="utf-8")
    _git(tmp, "commit", "-q", "-am", "c2")
    return c1, _git(tmp, "rev-parse", "HEAD")


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_writer_is_refused_until_expiry(self):
        branch_guard.acquire(self.project, "agy/u1-x", tool="agy", session="s1", ttl=60, now=1000.0)
        with self.assertRaises(branch_guard.LeaseHeld):
            branch_guard.acquire(self.project, "agy/u1-x", tool="claude", session="c1", now=1010.0)
        renewed = branch_guard.acquire(self.project, "agy/u1-x", tool="antigravity", session="s1", now=1020.0)
        self.assertEqual(renewed["acquired_at"], 1000.0)
        taken = branch_guard.acquire(self.project, "agy/u1-x", tool="claude", session="c1", now=1020.0 + 3600 * 5)
        self.assertEqual(taken["tool"], "claude")

    def test_lease_check_denies_other_tool_and_unnamed_pusher(self):
        branch_guard.acquire(self.project, "agy/u1-x", tool="antigravity", session="s1")
        self.assertIn("LEASE_HELD", branch_guard.lease_check(self.project, "agy/u1-x", "claude")["reason"])
        self.assertIn("--tool", branch_guard.lease_check(self.project, "agy/u1-x", None)["reason"])
        self.assertIsNone(branch_guard.lease_check(self.project, "agy/u1-x", "agy", "s1"))
        self.assertIsNone(branch_guard.lease_check(self.project, "other/branch", "claude"))

    def test_only_holder_releases_and_listing_shows_live_holders(self):
        branch_guard.acquire(self.project, "agy/u1-x", tool="antigravity", session="s1")
        self.assertEqual([row["tool"] for row in branch_guard.leases(self.project)], ["antigravity"])
        self.assertFalse(branch_guard.release(self.project, "agy/u1-x", tool="claude"))
        self.assertTrue(branch_guard.release(self.project, "agy/u1-x", tool="antigravity", session="s1"))
        self.assertEqual(branch_guard.leases(self.project), [])
        self.assertTrue(branch_guard.lease_path(self.project, "agy/u1-x").is_file())  # nothing is deleted

    def test_parallel_acquires_leave_exactly_one_holder(self):
        results: list[str] = []
        barrier = threading.Barrier(8)

        def worker(index: int) -> None:
            barrier.wait()
            try:
                branch_guard.acquire(self.project, "agy/u1-x", tool=("claude", "antigravity")[index % 2],
                                     session=f"s{index}")
                results.append("ok")
            except branch_guard.LeaseHeld:
                results.append("held")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count("ok"), 1, results)

    def test_bad_branch_and_tool_are_refused(self):
        with self.assertRaises(ValueError):
            branch_guard.acquire(self.project, "../x", tool="claude")
        with self.assertRaises(ValueError):
            branch_guard.acquire(self.project, "a/b", tool="gpt")


class FreezeAndHeadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.c1, self.c2 = _repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def _request(self, head: str) -> None:
        requests.register(self.project, request_id="relay_" + "a" * 32, requester="claude", target="antigravity",
                          card="U1", head=head)

    def test_push_over_open_verdict_request_is_refused(self):
        self._request(self.c1)
        denied = branch_guard.freeze_check(self.project, "agy/u1-x")
        self.assertEqual(denied["decision"], "DENY")
        self.assertIn("VERDICT_FREEZE", denied["reason"])

    def test_supersede_records_stale_and_wakes_requester_once(self):
        self._request(self.c1)
        allowed = branch_guard.freeze_check(self.project, "agy/u1-x", supersede=True, actor="antigravity")
        self.assertEqual(allowed["decision"], "ALLOW")
        self.assertEqual(allowed["stale"][0]["new_head"], self.c2)
        ledger = (self.project / ".coord" / "verdict_freeze.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(ledger[0])["state"], "STALE")
        first = branch_guard.wake_stale(self.project, allowed["stale"][0])
        self.assertTrue(first.startswith("verdict_stale_"))
        self.assertEqual(branch_guard.wake_stale(self.project, allowed["stale"][0]), "")
        letter = json.loads((self.project / ".coord" / "mailbox" / "inbox" / f"{first}.json").read_text("utf-8"))
        self.assertEqual(json.dumps(letter).count("VERDICT STALE"), 3)

    def test_no_freeze_without_request_or_other_head(self):
        self.assertIsNone(branch_guard.freeze_check(self.project, "agy/u1-x"))
        self._request(self.c2)  # the request pins a head that is not the pushed one
        self.assertIsNone(branch_guard.freeze_check(self.project, "agy/u1-x"))

    def test_answered_request_no_longer_freezes(self):
        self._request(self.c1)
        path = requests._path(self.project, "relay_" + "a" * 32)
        row = json.loads(path.read_text(encoding="utf-8"))
        row["state"] = requests.ANSWER_OBSERVED
        path.write_text(json.dumps(row), encoding="utf-8")
        self.assertIsNone(branch_guard.freeze_check(self.project, "agy/u1-x"))

    @staticmethod
    def _short(sha: str, size: int) -> str:
        # An all-digit prefix reads as a number, not a sha (by design); a random commit has one ~2% of the time at 8.
        while sha[:size].isdigit():
            size += 1
        return sha[:size]

    def test_short_sha_is_resolved_to_the_full_head(self):
        message = f"PASS PR #9 at {self._short(self.c2, 9)}"
        self.assertEqual(branch_guard.embed_full_head(self.project, message), f"{message} head={self.c2}")
        full = f"PASS at {self.c2}"
        self.assertEqual(branch_guard.embed_full_head(self.project, full), full)
        both = f"PASS deadbee then {self._short(self.c2, 8)}"
        self.assertEqual(branch_guard.embed_full_head(self.project, both), both)  # ambiguous: unchanged
        self.assertEqual(branch_guard.embed_full_head(self.project, "PASS 1234567"), "PASS 1234567")


class MergeGateTest(unittest.TestCase):
    HEAD = "b" * 40
    VIEW = {"state": "OPEN", "mergeable": "MERGEABLE", "headRefOid": HEAD, "headRefName": "agy/u1-x"}

    def test_full_head_in_delta_passes_the_gate(self):
        merge_route.gate(self.VIEW, self.HEAD, {"actor": "claude", "message": "PASS PR #9",
                                                "delta": f"head={self.HEAD}"})

    def test_head_in_neither_field_is_refused(self):
        with self.assertRaises(merge_route.MergeRefused):
            merge_route.gate(self.VIEW, self.HEAD, {"actor": "claude", "message": "PASS PR #9", "delta": "ok"})

    def test_revise_with_head_in_delta_is_refused(self):
        with self.assertRaises(merge_route.MergeRefused):
            merge_route.gate(self.VIEW, self.HEAD, {"actor": "claude", "message": "REVISE",
                                                    "delta": self.HEAD})


class ScheduleCloseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / ".coord").mkdir()
        self.path = self.project / ".coord" / "master_schedule.json"
        self.path.write_text(json.dumps({"phases": [
            {"phase_id": "U295", "state": "READY", "owner_tool": "codex"},
            {"phase_id": "U29", "state": "READY", "owner_tool": "codex"},
            {"phase_id": "U296", "state": "DONE", "owner_tool": "claude"}]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_title_cards_close_and_others_stay(self):
        closed = branch_guard.close_merged_phases(self.project, title="[U295][U296] fix", pr=262, head="c" * 40)
        self.assertEqual(closed, ["U295"])
        phases = {p["phase_id"]: p for p in json.loads(self.path.read_text(encoding="utf-8"))["phases"]}
        self.assertEqual(phases["U295"]["state"], "DONE")
        self.assertIn("PR #262", phases["U295"]["note"])
        self.assertEqual(phases["U29"]["state"], "READY")
        self.assertEqual(list(self.project.glob(".coord/.master_schedule.json.*.tmp")), [])

    def test_after_merge_closes_and_releases_lease(self):
        branch_guard.acquire(self.project, "claude/u295-x", tool="claude", session="s")
        done = merge_route.after_merge(self.project, {"title": "[U295] x", "headRefName": "claude/u295-x"},
                                       262, "c" * 40)
        self.assertEqual(done, {"closed_phases": ["U295"], "lease_released": True})


class WakeRerouteTest(unittest.TestCase):
    def test_away_owner_goes_to_conductor_or_nobody(self):
        desk = {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}
        self.assertEqual(branch_guard.wake_recipient("codex", desk), "claude")
        self.assertEqual(branch_guard.wake_recipient("antigravity", desk), "antigravity")
        desk["claude"] = {"state": "UNKNOWN"}
        self.assertIsNone(branch_guard.wake_recipient("codex", desk))

    def test_wake_owners_reroutes_a_limited_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".coord").mkdir()
            (project / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": [
                {"phase_id": "U9", "state": "READY", "owner_tool": "codex"}]}), encoding="utf-8")
            published = []

            class Box:
                def has_message(self, _mid):
                    return False

                def publish(self, message_id, payload):
                    published.append(payload)

            desk = {"codex": {"state": "LIMITED"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}
            from v7_harness.coord import presence
            saved = presence.read_all
            presence.read_all = lambda *_a, **_k: desk
            try:
                owner_wake.wake_owners(project, Box(), now=time.time())
                owner_wake.wake_owners(project, Box(), now=time.time() + 10 ** 6)
            finally:
                presence.read_all = saved
            self.assertEqual([p["recipient"] for p in published], ["claude"])
            self.assertIn("owner codex away", published[0]["wake_reason"])


if __name__ == "__main__":
    unittest.main()
