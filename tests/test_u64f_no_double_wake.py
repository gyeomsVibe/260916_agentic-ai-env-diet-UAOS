"""U64-F: one letter must not buy two paid Claude turns (Claude acting conductor, 2026-09-28).

Seen on relay_2175dda1: `coord deliver` dispatched a cold `claude -p` (receipt in delivery/accepted) and the live
interactive session's `coord watch` also woke on the same inbox letter. A letter that a dispatcher has already
handed to a Claude process is answered; the watcher skips it and still wakes on letters nobody dispatched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.watch import watch


class NoDoubleWake(unittest.TestCase):
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
