"""U214: a verdict request that was already dispatched is still a wait until it is acked, answered or its card ends.

Receipt (2026-10-18, user report "왜? 또 멈춰있는 것인가?" and roundtable memo
.work/desk261018/ROUNDTABLE_stall_root_cause.md E1/E2): `.coord/stall/seen.json` was `{}` while the whole desk waited.
`stall._letter_waits` read only `delivery/queued/<target>/*.json`, but deliver dispatches at once, so a sent request
lives only in `mailbox/inbox/` until `coord ack` moves it to `mailbox/ack/`. No wait was ever seen, so no reroute fired.
Codex relay_66465973 contract: close on ACK, in_reply_to and terminal card; immutable dispatch time; explicit active
watermark; malformed input controls. Antigravity CE1 (relay_89507a36): history must not burst into reroutes.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import presence, stall

HOUR = 3600.0


class DispatchedWait(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".coord").mkdir()
        for tool in ("claude", "antigravity"):
            presence.mark(self.root, tool, "ACTIVE")
        self.mailbox = self.root / ".coord" / "mailbox"
        self._watermark({"since": time.time() - 3 * HOUR})

    def _watermark(self, record):
        path = self.root / ".coord" / "stall" / "watermark.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record if isinstance(record, str) else json.dumps(record), encoding="utf-8")

    def _letter(self, name, *, folder="inbox", target="codex", actor="claude", sent_ago=2 * HOUR, requested=True,
                wake="ACTIONABLE", receipt=True, **extra):
        body = {"actor": actor, "requested_target": target, "wake_class": wake, "kind": "HANDOFF",
                "verdict_requested": requested, "message": "review U1", **extra}
        path = self.mailbox / folder / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"message_id": name, "payload": body, "schema": "u23-mailbox-v1"}),
                        encoding="utf-8")
        if receipt:
            self._receipt(name, int((time.time() - sent_ago) * 1e9))
        return path

    def _receipt(self, name, stamp):
        path = self.mailbox / "delivery" / "accepted" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"message_id": name, "state": "DISPATCHED", "timestamp_ns": stamp}),
                        encoding="utf-8")

    def _schedule(self, phases):
        (self.root / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": phases}), encoding="utf-8")

    def _items(self):
        return [entry["item"] for entry in stall.scan(self.root, "claude")["stalled"]]

    # --- the defect -------------------------------------------------------------------------------------------
    def test_a_dispatched_unacked_request_is_a_wait(self):
        self._letter("relay_a")
        found = stall.scan(self.root, "claude")["stalled"]
        self.assertEqual(["letter:codex:relay_a"], [e["item"] for e in found])
        self.assertEqual("antigravity", found[0]["owner"])  # verdict route with Codex away, never its author

    def test_a_letter_both_queued_and_dispatched_counts_once(self):
        self._letter("relay_a")
        queued = self.mailbox / "delivery" / "queued" / "codex" / "relay_a.json"
        queued.parent.mkdir(parents=True)
        queued.write_text(json.dumps({"actor": "claude", "message": "VERDICT_REQUESTED=YES", "message_id": "relay_a"}),
                          encoding="utf-8")
        then = time.time() - 2 * HOUR
        os.utime(queued, (then, then))
        self.assertEqual(["letter:codex:relay_a"], self._items())

    # --- closing a wait ---------------------------------------------------------------------------------------
    def test_ack_closes_the_wait(self):
        path = self._letter("relay_a")
        ack = self.mailbox / "ack" / path.name
        ack.parent.mkdir(parents=True)
        path.replace(ack)
        self.assertEqual([], self._items())

    def test_a_reply_with_in_reply_to_closes_the_wait(self):
        self._letter("relay_a")
        self._letter("relay_r", target="claude", actor="codex", requested=False, in_reply_to="relay_a")
        self.assertEqual([], self._items())

    def test_an_acked_reply_still_closes_the_wait(self):
        self._letter("relay_a")
        self._letter("relay_r", folder="ack", target="claude", actor="codex", requested=False, in_reply_to="relay_a")
        self.assertEqual([], self._items())

    def test_in_reply_to_inside_a_json_message_closes_the_wait(self):
        self._letter("relay_a")
        self._letter("relay_r", target="claude", actor="codex", requested=False)
        path = self.mailbox / "inbox" / "relay_r.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["payload"]["message"] = json.dumps({"in_reply_to": "relay_a", "verdict": "PASS"})
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual([], self._items())

    def test_an_agy_auto_reply_closes_the_wait(self):
        self._letter("relay_a", target="antigravity")
        path = self._letter("relay_r", target="claude", actor="antigravity", requested=False)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["payload"]["message"] = "[agy-auto] re relay_a: VERDICT: GO"
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual([], self._items())

    def test_a_reply_to_another_letter_does_not_close_it(self):
        self._letter("relay_a")
        self._letter("relay_r", target="claude", actor="codex", requested=False, in_reply_to="relay_other")
        self.assertIn("letter:codex:relay_a", self._items())

    def test_a_terminal_card_closes_the_wait(self):
        self._letter("relay_a", card="U9")
        self._schedule([{"phase_id": "U9", "state": "DONE"}])
        self.assertEqual([], self._items())

    def test_a_live_card_keeps_the_wait(self):
        self._letter("relay_a", card="U9")
        self._schedule([{"phase_id": "U9", "state": "READY", "owner_tool": "claude"}])
        self.assertIn("letter:codex:relay_a", self._items())

    # --- time semantics ---------------------------------------------------------------------------------------
    def test_age_comes_from_the_dispatch_receipt_not_the_file_time(self):
        path = self._letter("relay_a")
        now = time.time()
        os.utime(path, (now, now))  # a rewrite or copy moves mtime; the dispatch moment does not move
        found = stall.scan(self.root, "claude")["stalled"]
        self.assertEqual(["letter:codex:relay_a"], [e["item"] for e in found])
        self.assertGreaterEqual(found[0]["age_s"], 2 * HOUR - 60)

    def test_a_request_under_the_wait_limit_is_not_stalled(self):
        self._letter("relay_a", sent_ago=stall.MAX_WAIT_S - 120)
        self.assertEqual([], self._items())

    def test_letters_dispatched_before_the_watermark_are_history(self):
        self._letter("relay_old", sent_ago=4 * HOUR)
        self.assertEqual([], self._items())

    def test_a_missing_watermark_is_written_once_and_holds_back_history(self):
        (self.root / ".coord" / "stall" / "watermark.json").unlink()
        self._letter("relay_old")
        self.assertEqual([], self._items())
        mark = json.loads((self.root / ".coord" / "stall" / "watermark.json").read_text(encoding="utf-8"))["since"]
        self.assertAlmostEqual(time.time(), mark, delta=60)
        self.assertEqual([], self._items(), "a second scan must not move the watermark")
        self.assertEqual(mark, json.loads((self.root / ".coord" / "stall" / "watermark.json")
                                          .read_text(encoding="utf-8"))["since"])

    # --- malformed input --------------------------------------------------------------------------------------
    def test_a_note_or_info_letter_is_not_a_wait(self):
        self._letter("relay_note", requested=False)
        self._letter("relay_info", wake="INFO")
        self._letter("relay_str", requested="true")
        self.assertEqual([], self._items())

    def test_a_letter_without_a_valid_dispatch_receipt_is_not_a_dispatched_wait(self):
        self._letter("relay_none", receipt=False)
        self._letter("relay_bad", receipt=False)
        self._receipt("relay_bad", "123")
        self._letter("relay_neg", receipt=False)
        self._receipt("relay_neg", -5)
        self.assertEqual([], self._items())

    def test_unreadable_letters_events_and_shapes_are_skipped(self):
        inbox = self.mailbox / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "relay_bad.json").write_text("{", encoding="utf-8")
        (inbox / "relay_list.json").write_text(json.dumps({"payload": []}), encoding="utf-8")
        self._letter("evt_x")
        self._letter("relay_r", target="claude", actor="codex", requested=False, in_reply_to=["relay_a"])
        self.assertEqual([], self._items())

    def test_a_corrupt_watermark_counts_nothing_and_never_raises(self):
        for record in ("{", json.dumps([]), json.dumps({"since": "x"}), json.dumps({"since": True})):
            self._watermark(record)
            self._letter("relay_a")
            self.assertEqual([], self._items(), record)


if __name__ == "__main__":
    unittest.main()
