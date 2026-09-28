"""U76-A (Codex contract relay_5f04843b): token savings count only matched controlled pairs.

A pair is one `baseline_paid` row and one `thrift` row with the same comparison_id, input hash, acceptance hash,
task type, and model family, both PASS and checked by someone other than the actor. Fewer than 10 valid pairs is
UNMEASURED; the latest 10 are the decision window; older pairs stay as history with zero weight. Nothing is deleted.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord.token_savings import WINDOW, report

METRICS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "wall_time_s")


def _row(cid: str, role: str, ts: float, *, tokens: int, family: str = "gpt-5", outcome: str = "PASS",
         verifier: str | None = "codex", actor: str = "claude", input_hash: str = "i1", rework: int = 0,
         **overrides) -> dict:
    row = {
        "schema": "uaos-usage-v2", "work_id": f"W-{cid}-{role}", "actor": actor, "model": family, "kind": "pilot",
        "collection_mode": "manual", "input_tokens": tokens, "output_tokens": tokens // 10,
        "cache_read_input_tokens": tokens * 2, "cache_creation_input_tokens": 0, "wall_time_s": 10.0,
        "outcome": outcome, "receipt": "r", "independent_verifier": verifier, "rsi_eligible": True,
        "exclusion_reason": None, "ts": ts,
        "comparison": {"comparison_id": cid, "role": role, "input_hash": input_hash, "acceptance_hash": "a1",
                       "task_type": "summary", "model_family": family, "rework": rework},
    }
    row.update(overrides)
    return row


def _pair(n: int, *, base: int = 1000, thrift: int = 400, ts: float | None = None) -> list[dict]:
    at = float(ts if ts is not None else 1000 + n)
    return [_row(f"c{n}", "baseline_paid", at, tokens=base), _row(f"c{n}", "thrift", at + 0.5, tokens=thrift)]


class TokenSavingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord" / "usage").mkdir(parents=True)
        self.ledger = self.root / ".coord" / "usage" / "runs.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rows: list[dict], extra_lines: tuple[str, ...] = ()) -> None:
        lines = [json.dumps(row) for row in rows] + list(extra_lines)
        self.ledger.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))

    def _report(self) -> dict:
        return report(self.root)

    def test_window_is_ten_like_u55_and_u56(self) -> None:
        self.assertEqual(10, WINDOW)

    def test_rows_without_a_comparison_envelope_are_ignored_not_counted_as_savings(self) -> None:
        self._write([{"schema": "uaos-usage-v2", "work_id": "old", "kind": "pilot", "input_tokens": 5}])
        result = self._report()
        self.assertEqual("UNMEASURED", result["status"])
        self.assertEqual(0, result["valid_pairs"])
        self.assertEqual(1, result["rows_without_comparison"])
        self.assertIsNone(result["window"])

    def test_unmatched_rows_are_excluded_with_counts(self) -> None:
        rows = [_row("c1", "baseline_paid", 1, tokens=100)]  # no thrift partner
        rows += [_row("c2", "baseline_paid", 2, tokens=100), _row("c2", "thrift", 3, tokens=50, input_hash="other")]
        self._write(rows)
        result = self._report()
        self.assertEqual(0, result["valid_pairs"])
        self.assertEqual(1, result["excluded"]["unmatched"])
        self.assertEqual(1, result["excluded"]["incomplete"])

    def test_nine_pairs_stay_unmeasured(self) -> None:
        self._write([row for n in range(9) for row in _pair(n)])
        result = self._report()
        self.assertEqual("UNMEASURED", result["status"])
        self.assertEqual(9, result["valid_pairs"])
        self.assertIsNone(result["window"])
        self.assertFalse(result["savings_claim_allowed"])

    def test_exactly_ten_pairs_are_measured_per_metric(self) -> None:
        self._write([row for n in range(10) for row in _pair(n)])
        result = self._report()
        self.assertEqual("MEASURED", result["status"])
        window = result["window"]
        self.assertEqual(10, window["pairs"])
        self.assertEqual({"baseline_paid": 10000, "thrift": 4000, "saved": 6000},
                         {k: window["metrics"]["input_tokens"][k] for k in ("baseline_paid", "thrift", "saved")})
        self.assertEqual(set(METRICS), set(window["metrics"]))
        self.assertEqual([], window["regressions"])
        self.assertTrue(result["savings_claim_allowed"])

    def test_only_the_latest_ten_pairs_decide_and_older_pairs_stay_history(self) -> None:
        old = [row for n in range(5) for row in _pair(n, base=1000, thrift=5000, ts=10 + n)]  # old regressions
        new = [row for n in range(5, 15) for row in _pair(n, ts=100 + n)]
        self._write(old + new)
        result = self._report()
        self.assertEqual(15, result["valid_pairs"])
        self.assertEqual(5, result["history_pairs"])
        self.assertEqual([f"c{n}" for n in range(5, 15)], result["window"]["comparison_ids"])
        self.assertEqual([], result["window"]["regressions"])

    def test_cross_model_pairs_are_rejected(self) -> None:
        rows = [row for n in range(9) for row in _pair(n)]
        rows += [_row("x", "baseline_paid", 50, tokens=1000, family="gpt-5"),
                 _row("x", "thrift", 51, tokens=10, family="claude-opus")]
        self._write(rows)
        result = self._report()
        self.assertEqual("UNMEASURED", result["status"])
        self.assertEqual(1, result["excluded"]["cross_model"])

    def test_failed_acceptance_is_excluded(self) -> None:
        rows = [row for n in range(9) for row in _pair(n)]
        rows += [_row("f", "baseline_paid", 50, tokens=1000), _row("f", "thrift", 51, tokens=10, outcome="REWORK")]
        self._write(rows)
        result = self._report()
        self.assertEqual(9, result["valid_pairs"])
        self.assertEqual(1, result["excluded"]["failed"])

    def test_self_verified_or_unverified_rows_are_excluded(self) -> None:
        rows = [_row("s", "baseline_paid", 1, tokens=1000), _row("s", "thrift", 2, tokens=10, verifier="claude")]
        rows += [_row("u", "baseline_paid", 3, tokens=1000), _row("u", "thrift", 4, tokens=10, verifier=None)]
        self._write(rows)
        result = self._report()
        self.assertEqual(0, result["valid_pairs"])
        self.assertEqual(2, result["excluded"]["self_verified"])

    def test_duplicate_roles_exclude_the_whole_comparison(self) -> None:
        rows = [row for n in range(10) for row in _pair(n)]
        rows.append(_row("c3", "thrift", 2000, tokens=1))  # a second thrift row for c3 could cherry-pick the best run
        self._write(rows)
        result = self._report()
        self.assertEqual(9, result["valid_pairs"])
        self.assertEqual(1, result["excluded"]["duplicate"])
        self.assertEqual("UNMEASURED", result["status"])

    def test_malformed_and_secret_bearing_rows_are_counted_and_excluded(self) -> None:
        rows = [row for n in range(10) for row in _pair(n)]
        rows.append(_row("k", "baseline_paid", 60, tokens=5, receipt="sk-" + "a" * 30))
        bad_envelope = _row("m", "thrift", 61, tokens=5)
        bad_envelope["comparison"]["role"] = "other"
        rows.append(bad_envelope)
        self._write(rows, extra_lines=("{not json",))
        result = self._report()
        self.assertEqual(10, result["valid_pairs"])
        self.assertEqual(1, result["excluded"]["secret"])
        self.assertEqual(2, result["excluded"]["malformed"])  # the unreadable line and the unknown role

    def test_the_ledger_is_read_only(self) -> None:
        self._write([row for n in range(12) for row in _pair(n)])
        before = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        self._report()
        self.assertEqual(before, hashlib.sha256(self.ledger.read_bytes()).hexdigest())
        self.assertEqual(["runs.jsonl"], sorted(p.name for p in self.ledger.parent.iterdir()))

    def test_one_regressed_metric_is_reported_and_blocks_the_claim(self) -> None:
        rows = []
        for n in range(10):
            base, thrift = _pair(n)
            thrift["wall_time_s"] = 40.0  # fewer tokens but four times slower
            rows += [base, thrift]
        self._write(rows)
        result = self._report()
        self.assertEqual("MEASURED", result["status"])
        self.assertEqual(["wall_time_s"], result["window"]["regressions"])
        self.assertEqual(6000, result["window"]["metrics"]["input_tokens"]["saved"])
        self.assertFalse(result["savings_claim_allowed"])

    def test_one_pair_regression_cannot_hide_behind_a_positive_window_total(self) -> None:
        rows = []
        for n in range(10):
            base, thrift = _pair(n, base=1000, thrift=100)
            if n == 9:
                thrift["input_tokens"] = 1500
            rows += [base, thrift]
        self._write(rows)
        result = self._report()
        self.assertEqual(7600, result["window"]["metrics"]["input_tokens"]["saved"])
        self.assertEqual(["c9"], result["window"]["pair_regressions"]["input_tokens"])
        self.assertIn("input_tokens", result["window"]["regressions"])
        self.assertFalse(result["savings_claim_allowed"])

    def test_actual_model_mismatch_or_missing_model_is_cross_model(self) -> None:
        rows = [row for n in range(10) for row in _pair(n)]
        rows[-1]["model"] = "claude-opus"
        self._write(rows)
        mismatch = self._report()
        self.assertEqual(9, mismatch["valid_pairs"])
        self.assertEqual(1, mismatch["excluded"]["cross_model"])
        self.assertEqual("UNMEASURED", mismatch["status"])
        rows = [row for n in range(10) for row in _pair(n)]
        rows[-1]["model"] = None
        self._write(rows)
        missing = self._report()
        self.assertEqual(9, missing["valid_pairs"])
        self.assertEqual(1, missing["excluded"]["cross_model"])

    def test_more_rework_on_the_thrift_side_is_a_regression(self) -> None:
        rows = []
        for n in range(10):
            base, thrift = _pair(n)
            thrift["comparison"]["rework"] = 1
            rows += [base, thrift]
        self._write(rows)
        result = self._report()
        self.assertEqual({"baseline_paid": 0, "thrift": 10}, result["window"]["rework"])
        self.assertIn("rework", result["window"]["regressions"])

    def test_a_missing_metric_is_unknown_not_zero(self) -> None:
        rows = []
        for n in range(10):
            base, thrift = _pair(n)
            thrift["cache_creation_input_tokens"] = None
            rows += [base, thrift]
        self._write(rows)
        cache = self._report()["window"]["metrics"]["cache_creation_input_tokens"]
        self.assertIsNone(cache["saved"])
        self.assertEqual(10, cache["missing_pairs"])


if __name__ == "__main__":
    unittest.main()
