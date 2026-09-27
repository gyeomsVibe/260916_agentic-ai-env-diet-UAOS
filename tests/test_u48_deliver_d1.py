"""U48-D1: coord deliver keeps un-ACKed and failed letters, records the retry count and failure reason, loses none.

Gate (PLAN U48-D1): 8 parallel processes delivering 8 different letters lose 0; a letter without ACK stays in the
inbox; the failure reason is preserved; each dispatch attempt records its number. Separate from test_u48_deliver.py
so the D0 hash-pinned test file stays unchanged.
"""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox


class _Runner:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.calls = 0
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, argv, **kwargs):
        self.calls += 1
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def _deliver_distinct(project_text: str, index: int, results) -> None:
    runner = _Runner(0, json.dumps({"result": "accepted", "type": "result"}))
    with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
        outcome = deliver(Path(project_text), message=f"U48-D1 letter {index}", actor="codex", target="claude",
                          runner=runner)
    results.put({"id": outcome.message_id, "reason": outcome.reason, "calls": runner.calls})


def _receipts(project: Path, message_id: str) -> list[dict]:
    attempts = project / ".coord" / "mailbox" / "delivery" / "attempts"
    found = [json.loads(p.read_text(encoding="utf-8")) for p in attempts.glob(f"{message_id}_*.json")]
    return sorted(found, key=lambda receipt: receipt["timestamp_ns"])


class TestD1Retention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)

    def test_retry_count_and_failure_reason_are_recorded(self):
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            first = deliver(self.project, message="d1 retry", actor="codex", target="claude",
                            runner=_Runner(1, stderr="connection refused"))
            second = deliver(self.project, message="d1 retry", actor="codex", target="claude",
                             runner=_Runner(1, stderr="connection refused"))
            third = deliver(self.project, message="d1 retry", actor="codex", target="claude",
                            runner=_Runner(0, json.dumps({"result": "ok"})))
        receipts = _receipts(self.project, first.message_id)
        self.assertEqual([1, 2, 3], [receipt["attempt"] for receipt in receipts])
        self.assertEqual(["FAILED", "FAILED", "DISPATCHED"], [receipt["state"] for receipt in receipts])
        self.assertTrue(all("DELIVERY_FAILED" in receipt["reason"] for receipt in receipts[:2]), receipts)
        self.assertEqual("DISPATCHED", third.reason)
        self.assertEqual(first.message_id, second.message_id)
        inbox = self.project / ".coord" / "mailbox" / "inbox" / f"{first.message_id}.json"
        self.assertTrue(inbox.is_file())  # dispatched but not ACKed: the letter stays in the inbox

    def test_guard_recovery_receipt_is_not_counted_as_an_attempt(self):
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            first = deliver(self.project, message="d1 guard", actor="codex", target="claude",
                            runner=_Runner(1, stderr="refused"))
        attempts = self.project / ".coord" / "mailbox" / "delivery" / "attempts"
        (attempts / f"{first.message_id}_recovered.json").write_text(
            json.dumps({"message_id": first.message_id, "state": "GUARD_RECOVERED", "timestamp_ns": 0}),
            encoding="utf-8")
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            deliver(self.project, message="d1 guard", actor="codex", target="claude", runner=_Runner(1, stderr="x"))
        counted = [r["attempt"] for r in _receipts(self.project, first.message_id) if r["state"] != "GUARD_RECOVERED"]
        self.assertEqual([1, 2], counted)

    def test_eight_processes_eight_letters_lose_none(self):
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        workers = [ctx.Process(target=_deliver_distinct, args=(str(self.project), i, results)) for i in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(30)
            self.assertEqual(0, worker.exitcode)
        outcomes = [results.get(timeout=5) for _ in workers]
        ids = {outcome["id"] for outcome in outcomes}
        self.assertEqual(8, len(ids))
        self.assertEqual(["DISPATCHED"] * 8, [outcome["reason"] for outcome in outcomes], outcomes)
        self.assertEqual(8, sum(outcome["calls"] for outcome in outcomes))
        box = Mailbox(self.project / ".coord" / "mailbox")
        self.assertEqual(ids, {path.stem for path in box.inbox_dir.glob("*.json")})  # none lost, none ACKed away
        self.assertEqual([], list(box.ack_dir.glob("*.json")) if box.ack_dir.is_dir() else [])
        for message_id in ids:
            self.assertEqual([1], [r["attempt"] for r in _receipts(self.project, message_id)])


if __name__ == "__main__":
    unittest.main()
