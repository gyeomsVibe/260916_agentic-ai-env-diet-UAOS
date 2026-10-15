"""U193: the Antigravity auto-answer never records ANSWERED or acks a letter whose reply `deliver()` refused.

Fixed acceptance, written by the implementer before the change (judge: Codex). Live receipt 2026-10-15: a reply that
began "AUDIT PASS" was sent as NOTICE, the U188 rule refused it as UNSTRUCTURED_VERDICT, and the dispatcher still
recorded ANSWERED and acked the request, so reply relay_3cd721f8 existed nowhere.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import agy_dispatch, presence
from v7_harness.coord import watch as W
from v7_harness.coord.deliver import DeliverResult
from v7_harness.coord.mailbox import Mailbox


def _runner(response):
    def runner(argv, **kwargs):
        envelope = {"status": "SUCCESS", "conversation_id": "c", "response": response,
                    "usage": {"input_tokens": 10, "output_tokens": 5}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(envelope).encode(), stderr=b"")
    return runner


class RefusedReply(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()
        self.box = Mailbox(self.project / ".coord" / "mailbox")
        digest = hashlib.sha256(self._tmp.name.encode()).hexdigest()
        self.request = "relay_" + digest[:32]
        self.box.publish(self.request, {"kind": "HANDOFF", "actor": "claude", "message": "please audit",
                                        "digest": digest, "requested_target": "antigravity"})

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def rows(self):
        if not agy_dispatch._ledger(self.project).exists():
            return []
        return [json.loads(line) for line in
                agy_dispatch._ledger(self.project).read_text(encoding="utf-8").splitlines()]

    def dispatch(self, response):
        return agy_dispatch.dispatch(self.project, message_id=self.request, actor="claude",
                                     message="please audit", runner=_runner(response))

    def test_verdict_inside_first_line_is_sent_structured(self):
        row = self.dispatch("AUDIT PASS: the diff matches the contract.")
        self.assertEqual("ANSWERED", row["state"])
        stored = self.box.read_message(row["reply_id"])
        self.assertIsNotNone(stored, "the recorded reply id must exist in the mailbox")
        payload = stored["payload"]
        self.assertEqual("PASS", payload.get("verdict"))
        self.assertEqual("ACTIONABLE", W.classify(payload)[0])

    def test_refused_reply_is_failed_and_not_acked(self):
        refused = DeliverResult(False, "claude", "UNSTRUCTURED_VERDICT", (), "diag", "relay_" + "0" * 32, "d")
        with mock.patch("v7_harness.coord.deliver.deliver", return_value=refused):
            row = self.dispatch("Noted.")
        self.assertEqual("FAILED", row["state"])
        self.assertEqual("UNSTRUCTURED_VERDICT", row["error"])
        self.assertNotIn("ANSWERED", [r.get("state") for r in self.rows()])
        self.assertIsNotNone(self.box.claim(self.request, consumer_id="probe"),
                             "a refused reply must leave the request unacked for a retry")
        record = json.loads(self.kept().read_text(encoding="utf-8"))
        self.assertEqual("Noted.", record["envelope"]["response"],
                         "the raw Antigravity response must survive a refused delivery (no paid re-run); it stays outside "
                         "agy_box, the call's working folder, which U120 keeps empty")
        self.assertEqual((self.request, "claude"), (record["message_id"], record["recipient"]))

    # Codex REVISE relay_07a4b4d5: a second dispatch of the same request paid the provider again and overwrote the
    # first evidence. The kept reply is replayed with the provider forbidden; a bad cache fails closed.
    def kept(self):
        return self.project / ".coord" / "mailbox" / "delivery" / "agy_replies" / f"{self.request}.json"

    def reserved(self):
        return [r for r in self.rows() if r.get("state") == "RESERVED"]

    def forbidden(self, argv, **kwargs):
        # The same runner also carries the reply's own delivery to Claude; only the Antigravity call is forbidden.
        if any("to Antigravity in UAOS-RSI" in str(arg) for arg in argv):
            raise AssertionError("the provider must not be called when a kept reply exists")
        return _runner("delivered")(argv, **kwargs)

    def refused_once(self, response):
        refused = DeliverResult(False, "claude", "UNSTRUCTURED_VERDICT", (), "diag", "relay_" + "0" * 32, "d")
        with mock.patch("v7_harness.coord.deliver.deliver", return_value=refused):
            self.assertEqual("FAILED", self.dispatch(response)["state"])

    def test_second_call_replays_the_kept_reply_without_the_provider(self):
        self.refused_once("AUDIT PASS: the diff matches the contract.")
        row = agy_dispatch.dispatch(self.project, message_id=self.request, actor="claude", message="please audit",
                                    runner=self.forbidden)
        self.assertEqual("ANSWERED", row["state"])
        self.assertEqual(1, len(self.reserved()), "a replay takes no new unit of the paid cap")
        self.assertEqual("PASS", self.box.read_message(row["reply_id"])["payload"].get("verdict"))
        self.assertIsNone(self.box.claim(self.request, consumer_id="probe"), "an answered request is acked")

    def test_refused_twice_keeps_the_first_evidence(self):
        self.refused_once("Noted.")
        first = self.kept().read_bytes()
        refused = DeliverResult(False, "claude", "UNSTRUCTURED_VERDICT", (), "diag", "relay_" + "0" * 32, "d")
        with mock.patch("v7_harness.coord.deliver.deliver", return_value=refused):
            row = agy_dispatch.dispatch(self.project, message_id=self.request, actor="claude",
                                        message="please audit", runner=self.forbidden)
        self.assertEqual("FAILED", row["state"])
        self.assertEqual(first, self.kept().read_bytes())
        self.assertEqual(1, len(self.reserved()))
        self.assertIsNotNone(self.box.claim(self.request, consumer_id="probe"))

    def check_fails_closed(self, content, error):
        self.kept().parent.mkdir(parents=True, exist_ok=True)
        self.kept().write_text(content, encoding="utf-8")
        before = len(self.reserved())
        row = agy_dispatch.dispatch(self.project, message_id=self.request, actor="claude", message="please audit",
                                    runner=self.forbidden)
        self.assertEqual(("FAILED", error), (row["state"], row["error"]))
        self.assertEqual(content, self.kept().read_text(encoding="utf-8"), "a bad cache is evidence; never rewrite it")
        self.assertEqual(before, len(self.reserved()), "a bad cache takes no unit of the paid cap")
        self.assertIsNotNone(self.box.claim(self.request, consumer_id="probe"))

    def test_malformed_cache_fails_closed(self):
        self.check_fails_closed("{not json", "REPLAY_MALFORMED")

    def test_cache_for_another_recipient_fails_closed(self):
        self.refused_once("Noted.")
        record = json.loads(self.kept().read_text(encoding="utf-8"))
        self.kept().unlink()
        self.check_fails_closed(json.dumps(dict(record, recipient="codex")), "REPLAY_MISMATCH")

    def test_cache_for_another_request_text_fails_closed(self):
        self.refused_once("Noted.")
        record = json.loads(self.kept().read_text(encoding="utf-8"))
        self.kept().unlink()
        self.check_fails_closed(json.dumps(dict(record, request_digest="0" * 64)), "REPLAY_MISMATCH")

    # Codex REVISE relay_b44a0472: two parallel dispatches of one request both passed the replay check and both paid
    # the provider (answer0/answer1), while the kept record held only one. One owner per request spans the whole call.
    def test_parallel_dispatch_of_one_request_calls_the_provider_once(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        entered, release = threading.Event(), threading.Event()
        calls = []

        def blocking(argv, **kwargs):
            if any("to Antigravity in UAOS-RSI" in str(arg) for arg in argv):
                calls.append(1)
                entered.set()
                release.wait(10)
                return _runner("AUDIT PASS: answer0")(argv, **kwargs)
            return _runner("delivered")(argv, **kwargs)

        def run():
            return agy_dispatch.dispatch(self.project, message_id=self.request, actor="claude",
                                         message="please audit", runner=blocking)

        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(run)
            self.assertTrue(entered.wait(10), "the first worker must reach the provider")
            second = pool.submit(run).result(10)
            release.set()
            first = first.result(10)
        self.assertEqual("REQUEST_BUSY", second["state"], "a second owner of a live request never calls the provider")
        self.assertEqual("ANSWERED", first["state"])
        self.assertEqual(1, len(calls))
        record = json.loads(self.kept().read_text(encoding="utf-8"))
        self.assertEqual("AUDIT PASS: answer0", record["envelope"]["response"])
        self.assertEqual(1, len(self.reserved()))

    def test_answered_request_is_never_sent_twice(self):
        first = self.dispatch("AUDIT PASS: the diff matches the contract.")
        self.assertEqual("ANSWERED", first["state"])
        sends = []
        with mock.patch("v7_harness.coord.deliver.deliver", side_effect=lambda *a, **k: sends.append(1)):
            row = agy_dispatch.dispatch(self.project, message_id=self.request, actor="claude",
                                        message="please audit", runner=self.forbidden)
        self.assertEqual("ALREADY_ANSWERED", row["state"])
        self.assertEqual([], sends, "a replay after ANSWERED would mail the same reply twice")

    def test_backlog_keeps_a_letter_whose_request_is_busy(self):
        from v7_harness.coord.stream import _try_lock, _unlock

        agy_dispatch._park(self.project, message_id=self.request, actor="claude", message="please audit", card="",
                           now=1.0)
        parked = list(agy_dispatch._backlog(self.project).glob("*.json"))
        self.assertEqual(1, len(parked))
        lock = agy_dispatch._replay_path(self.project, self.request).with_suffix(".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR)
        try:
            self.assertTrue(_try_lock(fd))
            rows = agy_dispatch.drain_backlog(self.project, runner=self.forbidden)
            _unlock(fd)
        finally:
            os.close(fd)
        self.assertEqual(["REQUEST_BUSY"], [r["state"] for r in rows])
        self.assertTrue(parked[0].exists(), "a busy request stays parked for the next drain")


if __name__ == "__main__":
    unittest.main()
