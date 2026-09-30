"""U97-I: the start-of-session inbox lists what may need action and only counts routine RUN notices."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.cli import INBOX_SUMMARY_LIMIT, main
from v7_harness.coord.mailbox import Mailbox


class InboxBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.project / ".coord" / "mailbox")
        for i in range(3):
            self.box.publish(f"evt_run_{i}", {"kind": "RUN", "summary": f"pilot U{i}: SUCCEEDED/PASS/APPLIED"})
        self.box.publish("verdict_req", {"kind": "VERDICT_REQUEST", "summary": "x" * 500})
        self.box.publish("wake_p1", {"p1_alert": True, "wake_reason": "STALE_LOCK"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _inbox(self, *extra: str) -> dict:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, main(["coord", "inbox", "--project", str(self.project), *extra]))
        return json.loads(out.getvalue())

    def test_default_counts_run_notices_and_caps_summaries(self) -> None:
        result = self._inbox()
        self.assertEqual({"verdict_req", "wake_p1"}, {m["id"] for m in result["messages"]})
        self.assertEqual({"RUN": 3}, result["routine_counted"])
        verdict = next(m for m in result["messages"] if m["id"] == "verdict_req")
        self.assertEqual(INBOX_SUMMARY_LIMIT + 1, len(verdict["summary"]))

    def test_all_lists_everything_in_full(self) -> None:
        result = self._inbox("--all")
        self.assertEqual(5, len(result["messages"]))
        self.assertNotIn("routine_counted", result)
        verdict = next(m for m in result["messages"] if m["id"] == "verdict_req")
        self.assertEqual("x" * 500, verdict["summary"])

    def test_nothing_is_acked_or_moved(self) -> None:
        before = sorted(p.name for p in (self.project / ".coord" / "mailbox" / "inbox").glob("*.json"))
        self._inbox()
        after = sorted(p.name for p in (self.project / ".coord" / "mailbox" / "inbox").glob("*.json"))
        self.assertEqual(before, after)
        self.assertEqual(5, len(after))


if __name__ == "__main__":
    unittest.main()
