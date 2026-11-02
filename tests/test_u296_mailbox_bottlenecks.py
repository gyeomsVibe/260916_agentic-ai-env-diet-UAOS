"""U296: mailbox bottlenecks B5 (stop-gate noise), B6 (session-addressed letters), B11 (async Antigravity answer)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import requests, sentinel, watch
from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox


def _mine(session: str) -> dict:
    pid = os.getpid()
    return {"pid": pid, "process_created": watch.process_identity(pid), "token": f"t-{session}",
            "wakes_session": True, "session": session}


def _desk(root: Path, thread: str) -> None:
    path = root / ".coord" / "presence" / "user_desk_claude.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"thread": thread, "at": 1.0}), encoding="utf-8")


class SessionWatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_other_session_is_not_refused_same_session_is(self) -> None:
        taken, other = watch._take_locks(self.root, ("claude",), _mine("desk"))
        self.assertEqual((taken, other), (["claude"], None))
        _, other_child = watch._take_locks(self.root, ("claude",), _mine("child"))
        self.assertIsNone(other_child)
        _, again = watch._take_locks(self.root, ("claude",), _mine("desk"))
        self.assertEqual(again, "claude")

    def test_lock_and_lease_files_are_per_session(self) -> None:
        self.assertNotEqual(watch.lock_file(self.root, "claude", "a"), watch.lock_file(self.root, "claude", "b"))
        self.assertEqual(watch.lock_file(self.root, "claude").name, "claude.watch.lock.json")
        self.assertEqual(watch.watch_file(self.root, "claude").name, "claude.watch.json")

    def test_main_desk_takes_unaddressed_child_does_not(self) -> None:
        _desk(self.root, "desk")
        body = {"requested_target": "claude", "message": "x"}
        self.assertTrue(watch._session_eligible(self.root, "claude", body, "desk"))
        self.assertFalse(watch._session_eligible(self.root, "claude", body, "child"))

    def test_named_session_takes_only_its_letter(self) -> None:
        _desk(self.root, "desk")
        body = {"requested_target": "claude", "native_receiver": "child"}
        self.assertTrue(watch._session_eligible(self.root, "claude", body, "child"))
        self.assertFalse(watch._session_eligible(self.root, "claude", body, "desk"))

    def test_no_desk_record_leaves_unaddressed_letters_open(self) -> None:
        body = {"requested_target": "claude"}
        self.assertTrue(watch._session_eligible(self.root, "claude", body, "anyone"))

    def test_leases_of_two_sessions_coexist(self) -> None:
        for session in ("desk", "child"):
            watch._beat(self.root, ("claude",), f"t-{session}", 2.0, __import__("time").time(), True,
                        session=session, process_created=watch.process_identity(os.getpid()))
        self.assertTrue(watch.watcher_live(self.root, "claude"))
        self.assertEqual(len(watch._watch_records(self.root, "claude")), 2)
        self.assertEqual({r["session"] for r in watch._watch_records(self.root, "claude")}, {"desk", "child"})


class StopUnguardedNoiseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / ".coord").mkdir()

    def _register(self, rid: str, session: str) -> None:
        requests.register(self.root, request_id=rid, requester="claude", target="antigravity", card="U1",
                          subject="s", head="a" * 40, requester_session=session)

    def test_request_id_parsing(self) -> None:
        event = {"kind": "BLOCKED", "step": sentinel.STOP_UNGUARDED_STEP, "refs": ["request:relay_x"]}
        self.assertEqual(sentinel.stop_unguarded_request(event), "relay_x")
        self.assertIsNone(sentinel.stop_unguarded_request({"kind": "BLOCKED", "step": "U1"}))

    def test_noise_rules(self) -> None:
        _desk(self.root, "desk")
        self._register("relay_main", "desk")
        self._register("relay_child", "child")
        self.assertFalse(sentinel.stop_unguarded_is_noise(self.root, "relay_main"))
        self.assertTrue(sentinel.stop_unguarded_is_noise(self.root, "relay_child"))
        self.assertTrue(sentinel.stop_unguarded_is_noise(self.root, "relay_unknown"))

    def test_cycle_wakes_once_per_request_set(self) -> None:
        self._register("relay_main", "")
        (self.root / ".coord" / "mailbox").mkdir(parents=True)
        box = Mailbox(self.root / ".coord" / "mailbox")
        for index in range(3):  # three identical events for one request: the 8-per-turn flood
            box.publish(f"evt_{index}", {"kind": "BLOCKED", "step": sentinel.STOP_UNGUARDED_STEP,
                                         "refs": ["request:relay_main"], "ts": f"t{index}", "event_id": str(index)})
        first = sentinel.run_sentinel_cycle(self.root, box, recipient="claude")
        self.assertTrue(first["p1_wake_emitted"])
        wakes = [mid for mid, _ in box.peek() if mid.startswith("wake_")]
        self.assertEqual(len(wakes), 1)
        for mid in wakes:  # the wake is acknowledged; a fourth identical event must not wake again
            claim = box.claim(mid, consumer_id="t")
            box.ack(claim)
        box.publish("evt_9", {"kind": "BLOCKED", "step": sentinel.STOP_UNGUARDED_STEP,
                              "refs": ["request:relay_main"], "ts": "t9", "event_id": "9"})
        second = sentinel.run_sentinel_cycle(self.root, box, recipient="claude")
        self.assertFalse(second["p1_wake_emitted"])


class AsyncAgyDeliverTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / ".coord").mkdir()

    def _send(self, **extra):
        return deliver(self.root, message="please review", actor="claude", target="antigravity",
                       wake_class="ACTIONABLE", delta="review", **extra)

    def test_no_wait_returns_published_without_running_the_answer(self) -> None:
        with mock.patch("v7_harness.coord.agy_dispatch.dispatch_detached", return_value=True) as detached, \
                mock.patch("v7_harness.coord.agy_dispatch.dispatch") as sync:
            result = self._send(agy_wait=False)
        self.assertEqual(result.reason, "PUBLISHED")
        self.assertIn("AGY_DETACHED", result.output)
        detached.assert_called_once()
        sync.assert_not_called()

    def test_wait_keeps_the_synchronous_answer(self) -> None:
        with mock.patch("v7_harness.coord.agy_dispatch.dispatch_detached") as detached, \
                mock.patch("v7_harness.coord.agy_dispatch.dispatch", return_value={"state": "FAILED"}) as sync:
            result = self._send(agy_wait=True)
        self.assertEqual(result.reason, "PUBLISHED")
        sync.assert_called_once()
        detached.assert_not_called()

    def test_failed_spawn_falls_back_to_sync(self) -> None:
        with mock.patch("v7_harness.coord.agy_dispatch.dispatch_detached", return_value=False), \
                mock.patch("v7_harness.coord.agy_dispatch.dispatch", return_value={"state": "FAILED"}) as sync:
            self._send(agy_wait=False)
        sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
