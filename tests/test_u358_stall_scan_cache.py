"""U358: stall.scan() reads the mailbox once per scan and reuses an answered cache across scans.

Receipt (real use, 2026-11-22 09:12 KST, cProfile on the live repo): scan() took 4.83 s with 15,253 file opens and
13,150 JSON parses, because `_answered()` ran twice per scan over ~6,575 mailbox files, and `_inbox_waits()` opened
every letter before checking evt_/acked/answered. With prepare_delta the hook exceeded HOOK_ACK_BUDGET_S and the
desk-delta cursor ack was never written.
"""
import json
import time
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence, stall

HOUR = 3600.0


class StallScanCache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".coord").mkdir()
        for tool in ("claude", "antigravity"):
            presence.mark(self.root, tool, "ACTIVE")
        self.mailbox = self.root / ".coord" / "mailbox"
        mark = self.root / ".coord" / "stall" / "watermark.json"
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps({"since": time.time() - 3 * HOUR}), encoding="utf-8")
        self.cache = self.root / ".coord" / "stall" / "answered_cache.json"

    def _write(self, folder, name, body):
        path = self.mailbox / folder / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"message_id": name, "payload": body}), encoding="utf-8")
        return path

    def _request(self, name, folder="inbox", target="codex"):
        self._write(folder, name, {"actor": "claude", "requested_target": target, "wake_class": "ACTIONABLE",
                                   "kind": "HANDOFF", "verdict_requested": True, "message": "review U1"})
        receipt = self.mailbox / "delivery" / "accepted" / f"{name}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"message_id": name, "state": "DISPATCHED",
                                       "timestamp_ns": int((time.time() - 2 * HOUR) * 1e9)}), encoding="utf-8")

    def _reply(self, name, to, folder="ack"):
        return self._write(folder, name, {"actor": "codex", "in_reply_to": to, "message": "PASS"})

    def _items(self):
        return [e["item"] for e in stall.scan(self.root, "claude")["stalled"]]

    def _opens(self):
        real = stall._payload
        calls = []

        def spy(path):
            calls.append(Path(path).name)
            return real(path)
        return calls, mock.patch.object(stall, "_payload", side_effect=spy)

    def test_second_scan_reuses_cache_without_reopening_replies(self):
        for i in range(5):
            self._reply(f"relay_r{i}", f"relay_x{i}")
        self._items()
        self.assertTrue(self.cache.is_file())
        calls, patch = self._opens()
        with patch:
            self._items()
        self.assertEqual([], [c for c in calls if c.startswith("relay_r")], "cached replies must not be reopened")

    def test_new_or_edited_reply_invalidates_and_resolves(self):
        self._request("relay_a")
        self._request("relay_b")
        self._reply("relay_r0", "relay_zzz")
        self.assertEqual({"letter:codex:relay_a", "letter:codex:relay_b"}, set(self._items()))
        self._reply("relay_r1", "relay_a")  # added
        self.assertEqual(["letter:codex:relay_b"], self._items())
        path = self._reply("relay_r0", "relay_b")  # edited in place (size changes)
        self.assertTrue(path.is_file())
        self.assertEqual([], self._items())

    def test_corrupt_cache_rebuilds(self):
        self._request("relay_a")
        self._reply("relay_r1", "relay_a")
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        for junk in ("{not json", "[]", json.dumps({"ack/relay_r1.json": "bad"})):
            with self.subTest(junk=junk):
                self.cache.write_text(junk, encoding="utf-8")
                self.assertEqual([], self._items())
                self.assertIsInstance(json.loads(self.cache.read_text(encoding="utf-8")), dict)

    def test_inbox_waits_skips_evt_acked_and_answered_before_opening(self):
        self._request("relay_live")
        self._request("relay_acked")
        self._write("ack", "relay_acked", {"actor": "codex", "message": "ack copy"})
        self._request("relay_done")
        self._write("inbox", "evt_noise", {"actor": "x", "message": "event"})
        calls, patch = self._opens()
        dispatched = []
        real_at = stall._dispatched_at

        def at_spy(project, message_id):
            dispatched.append(message_id)
            return real_at(project, message_id)
        with patch, mock.patch.object(stall, "_dispatched_at", side_effect=at_spy):
            found = stall._inbox_waits(self.root, None, time.time(), answered={"relay_done"})
        self.assertEqual(["letter:codex:relay_live"], [w["item"] for w in found])
        for name in ("evt_noise", "relay_acked", "relay_done"):
            self.assertNotIn(f"{name}.json", calls)
            self.assertNotIn(name, dispatched)

    def test_answered_runs_once_per_scan(self):
        self._request("relay_a")
        real = stall._answered
        count = []

        def spy(project, mark):
            count.append(1)
            return real(project, mark)
        with mock.patch.object(stall, "_answered", side_effect=spy):
            self._items()
        self.assertEqual(1, len(count))

    def test_direct_callers_keep_working_without_answered(self):
        self._request("relay_a")
        self.assertEqual(["letter:codex:relay_a"],
                         [w["item"] for w in stall._inbox_waits(self.root, None, time.time())])
        self.assertEqual([], stall._letter_waits(self.root, None))


if __name__ == "__main__":
    unittest.main()
