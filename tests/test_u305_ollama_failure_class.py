from __future__ import annotations

import json
import unittest

from v7_harness.adapters.agy import _classify_provider_error, parse_agy_result
from v7_harness.rsi import REMEDIES, _cause


class TestU305OllamaFailureClass(unittest.TestCase):
    def test_classify_provider_error_maps_ollama_output_failures(self) -> None:
        self.assertEqual("NO_FILE_BLOCK", _classify_provider_error("model returned no file block"))
        self.assertEqual("SPLICE_UNSUPPORTED", _classify_provider_error("SPLICE_UNSUPPORTED:If"))
        self.assertEqual(
            "DICTATION_MISMATCH",
            _classify_provider_error("DICTATION_MISMATCH:v7_harness/coord/hud_live.py:0"),
        )
        self.assertEqual("SPLICE_SYNTAX", _classify_provider_error("SPLICE_SYNTAX:12"))
        self.assertEqual("PROMPT_TOO_LARGE", _classify_provider_error("PROMPT_TOO_LARGE: ~5000 tokens > 4096"))
        self.assertEqual("PROVIDER_ERROR", _classify_provider_error("ollama unreachable: timed out"))
        self.assertEqual("PROVIDER_ERROR", _classify_provider_error("some unknown failure string"))

    def test_parse_agy_result_uses_specific_ollama_class(self) -> None:
        env = {
            "status": "ERROR",
            "response": "bad reply",
            "usage": {"input_tokens": 5513, "output_tokens": 2496},
            "conversation_id": "ollama-local",
            "error": "model returned no file block",
        }
        out = parse_agy_result(stdout=json.dumps(env).encode("utf-8"), stderr=b"", exit_code=1)
        self.assertFalse(out.successful)
        self.assertEqual("NO_FILE_BLOCK", out.error_class)

    def test_rsi_cause_maps_historical_provider_error_rows(self) -> None:
        row_splice = {
            "outcome": "BLOCKED",
            "error_class": "PROVIDER_ERROR",
            "error_detail": "WorkerExecutionError: UNKNOWN_EFFECT_NEEDS_RECONCILIATION; worker: SPLICE_UNSUPPORTED:If",
        }
        self.assertEqual("SPLICE_UNSUPPORTED", _cause(row_splice))
        self.assertEqual("manual_template", REMEDIES["SPLICE_UNSUPPORTED"][0])
        self.assertEqual("manual_template", REMEDIES["SPLICE_SYNTAX"][0])
        row_dictation = {
            "outcome": "BLOCKED",
            "error_class": "PROVIDER_ERROR",
            "error_detail": "WorkerExecutionError: UNKNOWN_EFFECT_NEEDS_RECONCILIATION; worker: DICTATION_MISMATCH:v7_harness/coord/hud_live.py:0",
        }
        self.assertEqual("DICTATION_MISMATCH", _cause(row_dictation))
        row_timeout = {
            "outcome": "BLOCKED",
            "error_class": "PROVIDER_ERROR",
            "error_detail": "WorkerExecutionError: UNKNOWN_EFFECT_NEEDS_RECONCILIATION; worker: ollama unreachable: timed out",
        }
        self.assertEqual("PROVIDER_ERROR", _cause(row_timeout))


if __name__ == "__main__":
    unittest.main()
