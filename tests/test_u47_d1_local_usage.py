"""U47-D1 frozen acceptance (written by Claude): `rsi report` folds the local-model usage log in, without fake rows.

docs/48 §2 found 64 of 193 `pilot_local` rows were test leftovers with 1 input and 1 output token. They stay in the
file (never deleted) but must not count as real local work. Real rows are joined to the pilot ledger by work_id so a
local call can be traced to its pilot outcome.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import rsi
from v7_harness.cli import main


def _write(path: Path, rows: list) -> None:
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows), encoding="utf-8")


class LocalUsageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "usage.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fake_rows_are_counted_not_summed(self):
        _write(self.log, [
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 20.5, "model": "m", "work_id": "A",
             "input_tokens": 700, "output_tokens": 20},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 0.1, "input_tokens": 1, "output_tokens": 1},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 0.1, "input_tokens": 1, "output_tokens": 1},
        ])
        out = rsi.local_usage(self.log, [])
        self.assertEqual(3, out["rows"])
        self.assertEqual(2, out["fake_rows"])
        self.assertEqual(1, out["real"]["runs"])
        self.assertEqual(700, out["real"]["input_tokens"])
        self.assertEqual(20, out["real"]["output_tokens"])
        self.assertEqual(20.5, out["real"]["wall_s"])

    def test_other_events_and_bad_lines_are_ignored_but_counted(self):
        _write(self.log, [
            {"event": "ask", "input_tokens": 50, "output_tokens": 5},
            "not json",
            {"event": "pilot_local", "status": "ERROR", "elapsed_s": 3.0, "model": "m", "work_id": "B"},
        ])
        out = rsi.local_usage(self.log, [])
        self.assertEqual(1, out["rows"])
        self.assertEqual(1, out["unreadable"])
        self.assertEqual(1, out["real"]["runs"])
        self.assertEqual({"ERROR": 1}, out["real"]["by_status"])
        self.assertEqual(0, out["real"]["input_tokens"])

    def test_join_on_work_id(self):
        _write(self.log, [
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 1.0, "model": "m", "work_id": "A",
             "input_tokens": 10, "output_tokens": 2},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 1.0, "model": "m", "work_id": "Z",
             "input_tokens": 10, "output_tokens": 2},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 1.0, "input_tokens": 10, "output_tokens": 2},
        ])
        ledger = [{"kind": "pilot", "work_id": "A", "outcome": "PASS"}]
        out = rsi.local_usage(self.log, ledger)
        self.assertEqual(1, out["joined"])
        self.assertEqual(1, out["unjoined"])
        self.assertEqual(1, out["no_work_id"])
        self.assertEqual({"m": 2, "unknown": 1}, out["real"]["by_model"])

    def test_missing_log_is_reported_not_zero(self):
        out = rsi.local_usage(Path(self._tmp.name) / "absent.jsonl", [])
        self.assertFalse(out["present"])
        self.assertEqual(0, out["rows"])

    def test_note_keeps_cost_honest(self):
        _write(self.log, [])
        self.assertIn("not zero total cost", rsi.local_usage(self.log, [])["note"])

    def test_rsi_report_cli_includes_local(self):
        _write(self.log, [{"event": "pilot_local", "status": "GENERATED", "elapsed_s": 2.0, "model": "m",
                           "work_id": "A", "input_tokens": 9, "output_tokens": 3}])
        buffer = io.StringIO()
        with mock.patch("v7_harness.olla.USAGE_LOG", self.log), contextlib.redirect_stdout(buffer):
            self.assertEqual(0, main(["rsi", "report", "--project", self._tmp.name]))
        local = json.loads(buffer.getvalue())["local"]
        self.assertEqual(1, local["real"]["runs"])
        self.assertEqual(9, local["real"]["input_tokens"])


if __name__ == "__main__":
    unittest.main()
