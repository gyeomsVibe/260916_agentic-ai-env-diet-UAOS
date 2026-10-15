"""U197: the sentinel's zero-paid work-transition controller.
Receipt: .work/userdesk_261015/IDLE_ROOT_CAUSE.md causes 1, 4 and 5. A READY card sat unclaimed while its owner's
watcher was alive and never woken; an UNKNOWN desk told nobody to refresh it. The controller keeps a durable outbox
record per transition, wakes the owner by an ACTIONABLE letter, retries, escalates as P1, and never pays or writes the
schedule."""
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import presence, transition, watch
from v7_harness.coord.mailbox import Mailbox

T0 = 2_000_000_000.0


class TransitionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.root / ".coord" / "mailbox")
        self.schedule = self.root / ".coord" / "master_schedule.json"
        self._phases([{"phase_id": "U900", "state": "READY", "owner_tool": "claude"}])

    def tearDown(self):
        self.tmp.cleanup()

    def _phases(self, phases):
        self.schedule.parent.mkdir(parents=True, exist_ok=True)
        self.schedule.write_text(json.dumps({"phases": phases}), encoding="utf-8")

    def _desk(self, state="ACTIVE", now=T0):
        for tool in presence.TOOLS:
            presence.mark(self.root, tool, state, ttl_s=10 ** 6, now=now)

    def _letters(self):
        return {mid: body for mid, body in self.box.peek()}

    def _run(self, now):
        return transition.run_transitions(self.root, self.box, now=now)

    def test_ready_card_wakes_its_owner_once(self):
        self._desk()
        out = self._run(T0)
        self.assertEqual(out["paid_api_calls"], 0)
        self.assertEqual(len(out["published"]), 1, out)
        body = self._letters()[out["published"][0]]
        self.assertEqual(body["requested_target"], "claude")
        self.assertEqual(body["actor"], "sentinel")
        self.assertIn("U900", body["delta"])
        self.assertEqual(watch.classify(body)[0], "ACTIONABLE")
        self.assertEqual(self._run(T0 + 5)["published"], [])
        self.assertEqual(len(self._letters()), 1)

    def test_unclaimed_card_retries_then_escalates_once(self):
        self._desk()
        self._run(T0)
        step = transition.RETRY_S + 1
        for attempt in range(2, transition.MAX_ATTEMPTS + 1):
            out = self._run(T0 + step * (attempt - 1))
            self.assertEqual(len(out["published"]), 1, (attempt, out))
            self.assertTrue(out["published"][0].endswith(f"_{attempt}"))
        out = self._run(T0 + step * transition.MAX_ATTEMPTS)
        self.assertEqual(len(out["exhausted"]), 1, out)
        p1 = [b for b in self._letters().values() if b.get("kind") == "BLOCKED"]
        self.assertEqual(len(p1), 1)
        self.assertTrue(p1[0]["is_p1"])
        self.assertEqual(p1[0]["step"], "U900")
        self.assertEqual(p1[0]["requested_target"], "codex")
        self.assertEqual(watch.classify(p1[0])[0], "ACTIONABLE")
        later = self._run(T0 + step * (transition.MAX_ATTEMPTS + 3))
        self.assertEqual((later["published"], later["exhausted"]), ([], []))

    def test_a_claim_acks_and_stops_retries(self):
        self._desk()
        self._run(T0)
        claims = self.schedule.parent / "next" / "claims"
        claims.mkdir(parents=True)
        (claims / "U900.json").write_text(json.dumps({"session": "s1", "tool": "claude", "at": T0 + 5}),
                                          encoding="utf-8")
        out = self._run(T0 + transition.RETRY_S + 1)
        self.assertEqual(out["published"], [])
        self.assertEqual(len(out["acked"]), 1, out)

    def test_an_old_claim_by_another_tool_is_not_an_ack(self):
        self._desk()
        self._run(T0)
        claims = self.schedule.parent / "next" / "claims"
        claims.mkdir(parents=True)
        (claims / "U900.json").write_text(json.dumps({"session": "s0", "tool": "codex", "at": T0 - 10}),
                                          encoding="utf-8")
        out = self._run(T0 + transition.RETRY_S + 1)
        self.assertEqual(out["acked"], [])
        self.assertEqual(len(out["published"]), 1)

    def test_a_changed_row_acks_without_a_letter(self):
        self._desk()
        self._run(T0)
        self._phases([{"phase_id": "U900", "state": "DONE", "owner_tool": "claude"}])
        out = self._run(T0 + transition.RETRY_S + 1)
        self.assertEqual(out["published"], [])
        self.assertEqual(len(out["acked"]), 1, out)

    def test_unknown_desk_asks_live_watchers_to_refresh_presence_once(self):
        target = watch.watch_file(self.root, "claude")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"tool": "claude", "token": "t", "pid": 1, "expires_at": T0 + 600}),
                          encoding="utf-8")
        out = self._run(T0)
        unknown = [m for m in out["published"] if m.startswith("transition_unknown_")]
        self.assertEqual(len(unknown), 1, out)
        self.assertTrue(unknown[0].endswith("_claude"))
        self.assertEqual(watch.classify(self._letters()[unknown[0]])[0], "ACTIONABLE")
        again = self._run(T0 + 5)
        self.assertEqual([m for m in again["published"] if m.startswith("transition_unknown_")], [])

    def test_the_schedule_is_never_written(self):
        self._desk()
        before = self.schedule.read_bytes()
        for k in range(5):
            self._run(T0 + k * (transition.RETRY_S + 1))
        self.assertEqual(self.schedule.read_bytes(), before)

    def test_no_schedule_publishes_nothing(self):
        self.schedule.unlink()
        self._desk()
        out = self._run(T0)
        self.assertEqual(out["published"], [])

    def test_sentinel_cycle_reports_the_transition(self):
        from v7_harness.coord.sentinel import run_sentinel_cycle

        self._desk(now=None)
        res = run_sentinel_cycle(self.root, self.box)
        self.assertIn("transition", res)
        self.assertEqual(res["paid_api_calls"], 0)


if __name__ == "__main__":
    unittest.main()
