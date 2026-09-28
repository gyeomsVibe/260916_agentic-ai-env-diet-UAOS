"""U79: a call copied into a continued session's transcript is counted once across sessions.

Seen 2026-09-28: session f117861e (continued after compaction) repeated 7 message ids of session c2275161, 5 of them
with usage (about 442k tokens). U73 deduplicated only within one session, so recording both double-counted them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.session_usage import record_session


def _call(message_id: str, stamp: str, out: int) -> str:
    usage = {"input_tokens": 2, "output_tokens": out, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 10}
    return json.dumps({"type": "assistant", "timestamp": stamp,
                       "message": {"id": message_id, "model": "claude-opus-5-5", "usage": usage}})


class SessionDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _transcript(self, name: str, calls: list[str]) -> Path:
        path = self.root / f"{name}.jsonl"
        path.write_text("".join(line + "\n" for line in calls), encoding="utf-8")
        return path

    def _rows(self) -> list[dict]:
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_calls_copied_into_a_continued_session_are_not_counted_twice(self) -> None:
        first = self._transcript("sess-a", [_call("m1", "2026-09-28T00:00:01.000Z", 100),
                                            _call("m2", "2026-09-28T00:00:02.000Z", 50)])
        second = self._transcript("sess-b", [_call("m2", "2026-09-28T00:00:02.000Z", 50),  # copied from sess-a
                                             _call("m3", "2026-09-28T00:00:03.000Z", 7)])
        record_session(self.root, first, work_id="W", apply=True)
        result = record_session(self.root, second, work_id="W", apply=True)
        self.assertEqual(1, result["api_calls"])
        self.assertEqual(7, result["output_tokens"])
        self.assertEqual(1, result["duplicate_calls_skipped"])
        self.assertEqual(157, sum(row["output_tokens"] for row in self._rows()))

    def test_a_continued_session_of_only_copied_calls_records_nothing(self) -> None:
        first = self._transcript("sess-a", [_call("m1", "2026-09-28T00:00:01.000Z", 100)])
        second = self._transcript("sess-b", [_call("m1", "2026-09-28T00:00:01.000Z", 100)])
        record_session(self.root, first, work_id="W", apply=True)
        result = record_session(self.root, second, work_id="W", apply=True)
        self.assertEqual("NOTHING_NEW", result["mode"])
        self.assertEqual(1, len(self._rows()))

    def test_rows_keep_call_digests_not_raw_message_ids(self) -> None:
        first = self._transcript("sess-a", [_call("msg_secretlooking123", "2026-09-28T00:00:01.000Z", 1)])
        record_session(self.root, first, work_id="W", apply=True)
        row = self._rows()[0]
        self.assertEqual(1, len(row["call_digests"]))
        self.assertEqual(16, len(row["call_digests"][0]))
        self.assertNotIn("msg_secretlooking123", json.dumps(row))

    def test_dry_run_reports_the_skip_and_writes_nothing(self) -> None:
        first = self._transcript("sess-a", [_call("m1", "2026-09-28T00:00:01.000Z", 100)])
        second = self._transcript("sess-b", [_call("m1", "2026-09-28T00:00:01.000Z", 100),
                                             _call("m9", "2026-09-28T00:00:09.000Z", 3)])
        record_session(self.root, first, work_id="W", apply=True)
        result = record_session(self.root, second, work_id="W")
        self.assertEqual("DRY_RUN", result["mode"])
        self.assertEqual(1, result["duplicate_calls_skipped"])
        self.assertEqual(1, len(self._rows()))


if __name__ == "__main__":
    unittest.main()
