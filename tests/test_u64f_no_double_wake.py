"""U64-F: one letter must not buy two paid Claude turns (Claude acting conductor, 2026-09-28).

Seen on relay_2175dda1: `coord deliver` dispatched a cold `claude -p` (receipt in delivery/accepted) and the live
interactive session's `coord watch` also woke on the same inbox letter. A letter that a dispatcher has already
handed to a Claude process is answered; the watcher skips it and still wakes on letters nobody dispatched.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch


class NoDoubleWake(unittest.TestCase):
    def test_watcher_cannot_win_publish_to_receipt_race(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            ordering = []

            class Completed:
                returncode = 0
                stdout = json.dumps({"result": "processed", "is_error": False})
                stderr = ""

            real_publish = Mailbox.publish
            real_claim = Mailbox.claim

            def publish_spy(box, message_id, payload):
                pending = box.root / "delivery" / "pending" / f"{message_id}.json"
                ordering.append(("before_publish", pending.is_file()))
                return real_publish(box, message_id, payload)

            def claim_spy(box, message_id, claimer):
                pending = box.root / "delivery" / "pending" / f"{message_id}.json"
                record = json.loads(pending.read_text(encoding="utf-8"))
                ordering.append(("before_claim_owned", bool(record.get("owner"))))
                return real_claim(box, message_id, claimer)

            with (patch("v7_harness.coord.deliver.shutil.which", return_value="claude"),
                  patch.object(Mailbox, "publish", new=publish_spy),
                  patch.object(Mailbox, "claim", new=claim_spy)):
                result = deliver(project, message="ACTIONABLE_DELTA verdict_requested=yes: race",
                                 actor="codex", target="claude", runner=lambda *_args, **_kwargs: Completed())

            self.assertEqual("DISPATCHED", result.reason)
            self.assertEqual([("before_publish", True), ("before_claim_owned", True)], ordering)
            self.assertFalse((project / ".coord" / "mailbox" / "delivery" / "pending" /
                              f"{result.message_id}.json").exists())

    def test_guard_loser_cannot_remove_winners_pending_marker(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            (project / ".coord" / "mailbox").mkdir(parents=True)
            with patch("v7_harness.coord.deliver._acquire_guard", return_value=None):
                result = deliver(project, message="ACTIONABLE_DELTA verdict_requested=yes: contender",
                                 actor="codex", target="claude")
            self.assertEqual("IN_FLIGHT", result.reason)
            self.assertTrue((project / ".coord" / "mailbox" / "delivery" / "pending" /
                             f"{result.message_id}.json").is_file())

    def test_pending_failed_dispatch_becomes_visible_again(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            root = project / ".coord" / "mailbox"
            root.mkdir(parents=True)
            box = Mailbox(root)
            pending = root / "delivery" / "pending" / "relay_pending.json"
            ticks = {"n": 0}

            def sleep(_seconds: float) -> None:
                ticks["n"] += 1
                if ticks["n"] == 1:
                    box.publish("relay_pending", {"kind": "HANDOFF", "requested_target": "claude"})
                    pending.parent.mkdir(parents=True)
                    pending.write_text(json.dumps({"state": "PENDING"}), encoding="utf-8")
                elif ticks["n"] == 2:
                    pending.unlink()

            result = watch(project, ("claude",), timeout_s=60, interval_s=0, sleep=sleep)
            self.assertEqual("relay_pending", result["id"])

    def test_stale_pending_marker_does_not_suppress_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            root = project / ".coord" / "mailbox"
            root.mkdir(parents=True)
            box = Mailbox(root)
            pending = root / "delivery" / "pending" / "relay_stale.json"
            calls = {"n": 0}

            def sleep(_seconds: float) -> None:
                calls["n"] += 1
                if calls["n"] == 1:
                    box.publish("relay_stale", {"kind": "HANDOFF", "requested_target": "claude"})
                    pending.parent.mkdir(parents=True)
                    pending.write_text(json.dumps({"state": "PENDING"}), encoding="utf-8")
                    old = time.time() - 600
                    os.utime(pending, (old, old))

            result = watch(project, ("claude",), timeout_s=60, interval_s=0, sleep=sleep)
            self.assertEqual("relay_stale", result["id"])

    def test_dispatched_letter_is_skipped_undispatched_wakes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            root = project / ".coord" / "mailbox"
            root.mkdir(parents=True)
            box = Mailbox(root)
            calls = {"n": 0}

            def sleep(_seconds: float) -> None:
                calls["n"] += 1
                if calls["n"] == 1:
                    box.publish("relay_dispatched", {"kind": "HANDOFF", "requested_target": "claude"})
                    accepted = root / "delivery" / "accepted"
                    accepted.mkdir(parents=True)
                    (accepted / "relay_dispatched.json").write_text(json.dumps({"state": "DISPATCHED"}),
                                                                   encoding="utf-8")
                elif calls["n"] == 2:
                    box.publish("relay_queued", {"kind": "HANDOFF", "requested_target": "claude"})

            result = watch(project, ("claude",), timeout_s=60, interval_s=0, sleep=sleep)
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], "relay_queued")

    def test_failed_dispatch_still_wakes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            root = project / ".coord" / "mailbox"
            root.mkdir(parents=True)
            box = Mailbox(root)

            def sleep(_seconds: float) -> None:
                box.publish("relay_failed", {"kind": "HANDOFF", "requested_target": "claude"})
                attempts = root / "delivery" / "attempts"
                attempts.mkdir(parents=True, exist_ok=True)
                (attempts / "relay_failed_x.json").write_text(json.dumps({"state": "FAILED"}), encoding="utf-8")

            result = watch(project, ("claude",), timeout_s=60, interval_s=0, sleep=sleep)
            self.assertEqual(result["id"], "relay_failed")


if __name__ == "__main__":
    unittest.main()
