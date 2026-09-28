"""U78: API-equivalent prices weigh ledger tokens; unknown models are never guessed; the ledger is read-only."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord.price_table import PRICES, freshness, is_zero_paid, main, report, usd_equivalent


def _row(model, *, inp=0, out=0, cache_read=0, cache_write=0) -> dict:
    return {"model": model, "input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write}


class PriceTableTests(unittest.TestCase):
    def test_table_goes_stale_after_thirty_days_or_when_a_promo_price_expires(self) -> None:
        self.assertEqual("FRESH", freshness(date(2026, 10, 28))["status"])  # day 30
        late = freshness(date(2026, 10, 29))  # day 31
        self.assertEqual("STALE", late["status"])
        self.assertIsNotNone(late["refresh"])
        promo = dict(PRICES["gemini-3.8-flash"])
        self.assertEqual("2026-12-31", promo["valid_until"])
        with patch("v7_harness.coord.price_table.RETRIEVED", "2026-12-20"):
            self.assertEqual("FRESH", freshness(date(2026, 12, 31))["status"])
            expired = freshness(date(2027, 1, 1))
        self.assertEqual(["gemini-3.8-flash"], expired["expired_entries"])
        self.assertEqual("STALE", expired["status"])

    def test_check_flag_exits_one_only_when_stale(self) -> None:
        with patch("v7_harness.coord.price_table.date") as fake, patch("sys.stdout", new_callable=io.StringIO):
            fake.fromisoformat = date.fromisoformat
            fake.today.return_value = date(2026, 10, 1)
            self.assertEqual(0, main(["--check"]))
            fake.today.return_value = date(2026, 11, 30)
            self.assertEqual(1, main(["--check"]))

    def test_list_prices_match_the_vendor_pages_read_on_2026_09_28(self) -> None:
        self.assertEqual((4.00, 5.00, 0.20, 20.00), tuple(PRICES["claude-opus-5-5"][k] for k in
                                                          ("input", "cache_write", "cache_read", "output")))
        self.assertEqual((4.00, 0.40, 20.00), tuple(PRICES["gpt-5.6-sol"][k] for k in ("input", "cache_read", "output")))
        self.assertEqual((2.00, 0.20, 10.00), tuple(PRICES["gpt-6-sol"][k] for k in ("input", "cache_read", "output")))
        self.assertEqual((3.00, 0.30, 15.00),
                         tuple(PRICES["claude-sonnet-4-6"][k] for k in ("input", "cache_read", "output")))

    def test_every_vendor_charges_output_at_least_five_times_input_and_cache_reads_at_most_a_tenth(self) -> None:
        for model, price in PRICES.items():
            self.assertGreaterEqual(price["output"] / price["input"], 5.0, model)
            self.assertLessEqual(price["cache_read"] / price["input"], 0.1 + 1e-9, model)

    def test_one_row_is_priced_by_component(self) -> None:
        usd = usd_equivalent(_row("claude-opus-5-5", inp=1_000_000, out=100_000, cache_read=10_000_000,
                                  cache_write=200_000))
        self.assertEqual({"input": 4.0, "cache_write": 1.0, "cache_read": 2.0, "output": 2.0, "total": 9.0}, usd)

    def test_ambiguous_mixed_default_or_missing_models_are_not_guessed(self) -> None:
        for model in ("sonnet", "gpt-5.6-sol,gpt-6-sol", "agy-default", "codex-default", None, 7):
            self.assertIsNone(usd_equivalent(_row(model, inp=10)), model)

    def test_local_and_deterministic_workers_spend_no_paid_tokens(self) -> None:
        self.assertTrue(is_zero_paid("qwen2.5-coder:7b"))
        self.assertTrue(is_zero_paid("deterministic"))
        self.assertFalse(is_zero_paid("gpt-5.6-sol"))

    def test_report_totals_unpriced_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / ".coord" / "usage" / "runs.jsonl"
            ledger.parent.mkdir(parents=True)
            rows = [_row("gpt-5.6-sol", inp=1_000_000, out=1_000_000, cache_read=100_000_000),
                    _row("sonnet", inp=500), _row("qwen2.5-coder:7b", inp=900), _row("agy-default")]
            ledger.write_bytes(("\n".join(json.dumps(r) for r in rows) + "\n{bad\n").encode("utf-8"))
            before = hashlib.sha256(ledger.read_bytes()).hexdigest()
            result = report(Path(tmp))
            self.assertEqual(before, hashlib.sha256(ledger.read_bytes()).hexdigest())
        codex = result["priced_usd_equivalent"]["gpt-5.6-sol"]
        self.assertEqual(64.0, codex["total"])  # 4 input + 20 output + 40 cache read
        self.assertEqual("cache_read", codex["largest_component"])
        self.assertEqual(64.0, result["priced_total_usd_equivalent"])
        self.assertEqual({"rows": 1, "input_tokens": 500, "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0, "output_tokens": 0}, result["unpriced_tokens"]["sonnet"])
        self.assertNotIn("agy-default", result["unpriced_tokens"])  # no tokens, no cost
        self.assertEqual(1, result["zero_paid_rows"])
        self.assertEqual(1, result["malformed"])


if __name__ == "__main__":
    unittest.main()
