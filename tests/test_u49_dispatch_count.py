"""U49-D2: a dispatch receipt that is valid JSON but not an object is counted, not a crash (REDTEAM P3 on U48-D1)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.deliver import _dispatch_count


class DispatchCountTests(unittest.TestCase):
    def _write(self, attempts: Path, name: str, text: str) -> None:
        (attempts / name).write_text(text, encoding="utf-8")

    def test_non_object_json_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            attempts = Path(d)
            self._write(attempts, "m1_a.json", "[1, 2]")
            self._write(attempts, "m1_b.json", "7")
            self.assertEqual(2, _dispatch_count(attempts, "m1"))

    def test_guard_recovered_not_counted_and_other_states_counted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            attempts = Path(d)
            self._write(attempts, "m1_a.json", json.dumps({"state": "GUARD_RECOVERED"}))
            self._write(attempts, "m1_b.json", json.dumps({"state": "DISPATCHED"}))
            self._write(attempts, "m1_c.json", "not json")
            self._write(attempts, "m2_d.json", json.dumps({"state": "FAILED"}))
            self.assertEqual(2, _dispatch_count(attempts, "m1"))

    def test_missing_directory_counts_zero(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(0, _dispatch_count(Path(d) / "absent", "m1"))


if __name__ == "__main__":
    unittest.main()
