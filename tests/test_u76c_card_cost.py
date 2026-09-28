"""U76-C: a card over 3x the baseline card average fails and keeps the next card closed; missing data is UNKNOWN."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord.card_cost import RATIO_LIMIT, main, report


def _row(work_id, *, inp=0, out=0, cache_read=0, cache_write=0) -> dict:
    return {"work_id": work_id, "kind": "session", "input_tokens": inp, "output_tokens": out,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}


# The real U72/U74 numbers (docs/62): baseline 46,206,721 total / 235,078 output over 9 cards;
# U74 two rows plus U74-TAIL = 16,123,467 total / 69,482 output -> 3.14x total, 2.66x output.
U74_ROWS = [_row("U67-U73-ACTING", inp=1_000_000, out=235_078, cache_read=44_971_643),
            _row("U74", inp=300_000, out=48_990, cache_read=11_165_461),
            _row("U74", inp=100_000, out=14_108, cache_read=2_664_204),
            _row("U74-TAIL", inp=50_000, out=6_384, cache_read=1_774_320),
            _row("U75", inp=999_999_999)]


class CardCostTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = self.root / ".coord" / "usage" / "runs.jsonl"
        self.ledger.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rows, extra=()) -> None:
        self.ledger.write_bytes(("\n".join([json.dumps(r) for r in rows] + list(extra)) + "\n").encode("utf-8"))

    def test_limit_is_the_global_rule_three_times(self) -> None:
        self.assertEqual(3.0, RATIO_LIMIT)

    def test_u74_reproduces_the_hand_computed_fail(self) -> None:
        self._write(U74_ROWS)
        result = report(self.root, card="U74", baseline="U67-U73-ACTING", baseline_cards=9)
        self.assertEqual(16_123_467, result["card_usage"]["total_tokens"])
        self.assertEqual(3, result["card_usage"]["rows"])  # U74 x2 + U74-TAIL; U75 is another card
        self.assertEqual({"total_tokens": 3.14, "output_tokens": 2.66}, result["ratios"])
        self.assertEqual("FAIL", result["status"])
        self.assertEqual(["total_tokens"], result["over_limit"])
        self.assertFalse(result["next_card_allowed"])

    def test_within_limit_passes(self) -> None:
        self._write([_row("B", inp=900, out=90), _row("C", inp=250, out=25)])
        result = report(self.root, card="C", baseline="B", baseline_cards=3)
        self.assertEqual("PASS", result["status"])
        self.assertEqual({"total_tokens": 0.83, "output_tokens": 0.83}, result["ratios"])
        self.assertTrue(result["next_card_allowed"])

    def test_output_alone_over_the_limit_fails(self) -> None:
        self._write([_row("B", inp=1000, out=10), _row("C", inp=100, out=40)])
        result = report(self.root, card="C", baseline="B", baseline_cards=1)
        self.assertEqual(["output_tokens"], result["over_limit"])
        self.assertEqual("FAIL", result["status"])

    def test_exactly_three_times_is_not_over(self) -> None:
        self._write([_row("B", inp=100, out=10), _row("C", inp=300, out=30)])
        self.assertEqual("PASS", report(self.root, card="C", baseline="B", baseline_cards=1)["status"])

    def test_card_prefix_does_not_capture_other_cards(self) -> None:
        self._write([_row("B", inp=100, out=10), _row("U7", inp=100, out=10), _row("U70", inp=10**9, out=10**6)])
        result = report(self.root, card="U7", baseline="B", baseline_cards=1)
        self.assertEqual(1, result["card_usage"]["rows"])
        self.assertEqual("PASS", result["status"])

    def test_missing_card_baseline_or_bad_count_is_unknown_not_pass(self) -> None:
        self._write([_row("B", inp=100, out=10)])
        self.assertEqual("UNKNOWN", report(self.root, card="C", baseline="B", baseline_cards=1)["status"])
        self._write([_row("C", inp=100, out=10)])
        self.assertEqual("UNKNOWN", report(self.root, card="C", baseline="B", baseline_cards=1)["status"])
        self._write([_row("B", inp=100, out=10), _row("C", inp=100, out=10)])
        self.assertEqual("UNKNOWN", report(self.root, card="C", baseline="B", baseline_cards=0)["status"])

    def test_read_only_and_malformed_counted(self) -> None:
        self._write(U74_ROWS, extra=("{bad",))
        before = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        result = report(self.root, card="U74", baseline="U67-U73-ACTING", baseline_cards=9)
        self.assertEqual(before, hashlib.sha256(self.ledger.read_bytes()).hexdigest())
        self.assertEqual(1, result["malformed"])

    def _pin(self, text: str) -> None:
        (self.root / ".coord" / "card_baseline.json").write_text(text, encoding="utf-8")

    def test_exit_code_is_zero_only_on_pass(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            self._write(U74_ROWS + [_row("U80", inp=1_000_000, out=10_000)])
            project = ["--project", str(self.root)]
            self.assertEqual(1, main(project + ["--card", "U80"]))  # no pin: UNKNOWN
            self._pin(json.dumps({"baseline": "U67-U73-ACTING", "baseline_cards": 9}))
            self.assertEqual(0, main(project + ["--card", "U80"]))
            self.assertEqual(1, main(project + ["--card", "U74"]))  # 3.14x FAIL
            self.assertEqual(1, main(project + ["--card", "NONE"]))
            # U80 red team: choosing a smaller card count would make U74 pass; an override is exploratory only.
            out.seek(0)
            out.truncate()
            self.assertEqual(1, main(project + ["--card", "U74", "--baseline-cards", "1"]))
            shown = json.loads(out.getvalue())
            self.assertEqual("PASS", shown["status"])
            self.assertTrue(shown["exploratory"])

    def test_a_malformed_pin_is_unknown(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO):
            self._write(U74_ROWS)
            for text in ("{bad", json.dumps({"baseline": "U67-U73-ACTING", "baseline_cards": 0}),
                         json.dumps({"baseline": "", "baseline_cards": 9}), json.dumps([1])):
                self._pin(text)
                self.assertEqual(1, main(["--project", str(self.root), "--card", "U74"]), text)

    def test_the_committed_pin_is_the_u72_baseline(self) -> None:
        pin = json.loads((Path(__file__).resolve().parents[1] / ".coord" / "card_baseline.json").read_text("utf-8"))
        self.assertEqual(("U67-U73-ACTING", 9), (pin["baseline"], pin["baseline_cards"]))


if __name__ == "__main__":
    unittest.main()
