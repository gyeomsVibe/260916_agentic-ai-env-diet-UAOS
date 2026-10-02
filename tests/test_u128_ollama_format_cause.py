"""U128: an Ollama reply that drops or rewrites the dictated edit is a manual cause, not an Ollama outage.

Receipt (2026-10-02, `rsi propose`): proposal rsi_a097cb04dae9 read U125-L2, U125-L2R and U126-L as PROVIDER_ERROR and
advised "Check that the Ollama service and model are up", yet Ollama answered all three: U125-L2 and U125-L2R returned
the REPLACE text without its ===EDIT frame ("model returned no file block") and U126-L rewrote the dictated function
(DICTATION_MISMATCH). The remedy that worked each time was `worker: apply` with `apply_after` (U125-L3, U126-L2).
Fixed acceptance written by the judge (claude) before the run.
"""

from __future__ import annotations

import unittest

from v7_harness import rsi

PREFIX = "WorkerExecutionError: UNKNOWN_EFFECT_NEEDS_RECONCILIATION; worker: "


def _row(work_id: str, detail: str) -> dict:
    return {"work_id": work_id, "worker": "local", "outcome": "BLOCKED", "error_class": "PROVIDER_ERROR",
            "error_detail": PREFIX + detail}


class OllamaFormatCauseTest(unittest.TestCase):
    def test_a_frameless_reply_is_no_file_block(self) -> None:
        self.assertEqual("NO_FILE_BLOCK", rsi._cause(_row("U125-L2", "model returned no file block")))

    def test_a_rewritten_dictation_is_dictation_mismatch(self) -> None:
        row = _row("U126-L", "DICTATION_MISMATCH:v7_harness/adapters/ollama_worker.py:0")
        self.assertEqual("DICTATION_MISMATCH", rsi._cause(row))

    def test_both_causes_point_to_the_apply_route(self) -> None:
        for cause in ("NO_FILE_BLOCK", "DICTATION_MISMATCH"):
            target, action = rsi.REMEDIES[cause]
            self.assertEqual("manual_template", target)
            self.assertIn("worker: apply", action)
            self.assertIn("apply_after", action)

    def test_the_u125_u126_window_no_longer_blames_the_service(self) -> None:
        rows = [_row("U125-L2", "model returned no file block"), _row("U125-L2R", "model returned no file block"),
                _row("U126-L", "DICTATION_MISMATCH:v7_harness/adapters/ollama_worker.py:0")]
        info = rsi.analyze(rows, {**rsi.DEFAULT_POLICY, "min_samples": 1, "window": 3})["workers"]["local"]
        self.assertEqual({"NO_FILE_BLOCK": 2, "DICTATION_MISMATCH": 1}, dict(info["causes"]))
        self.assertEqual(["U125-L2", "U125-L2R"], info["cause_work_ids"]["NO_FILE_BLOCK"])

    def test_a_row_without_error_class_also_reads_the_phrase(self) -> None:
        row = {"outcome": "REWORK", "error_detail": "worker: model returned no file block"}
        self.assertEqual("NO_FILE_BLOCK", rsi._cause(row))

    def test_a_specific_class_is_not_overridden_by_the_phrase(self) -> None:
        # U81 rule; the U128-L2 Ollama bundle put the phrase loop outside the generic branch and broke it.
        row = {"outcome": "REWORK", "error_class": "SCOPE_VIOLATION", "error_detail": "model returned no file block"}
        self.assertEqual("SCOPE_VIOLATION", rsi._cause(row))

    def test_a_plain_provider_error_stays_a_provider_error(self) -> None:
        row = {"outcome": "BLOCKED", "error_class": "PROVIDER_ERROR", "error_detail": "connection refused"}
        self.assertEqual("PROVIDER_ERROR", rsi._cause(row))


if __name__ == "__main__":
    unittest.main()
