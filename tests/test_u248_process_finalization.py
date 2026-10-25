import subprocess
import sys
import unittest

from v7_harness.process_supervisor import terminate_with_finalization, verify_reconstruction
from v7_harness.rea_bridge import build_reconstruction_obligation_ledger


class TestU248ProcessFinalization(unittest.TestCase):
    def test_terminate_with_finalization_stops_process_cleanly(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        res = terminate_with_finalization(proc, finalization_ms=200)
        self.assertTrue(res["timed_out"])
        self.assertIsNone(res["exit_code"])
        self.assertGreaterEqual(len(res["finalization"]["signals"]), 1)
        self.assertEqual(res["finalization"]["signals"][0]["signal"], "SIGTERM")

    def test_verify_reconstruction_checks_finite_obligations(self):
        ledger = build_reconstruction_obligation_ledger(
            target_id="DXBALL",
            claims=[
                {"symbol": "sound_pan", "expected_behavior": "63-byte match", "oracle_cases": 3205},
                {"symbol": "clamp_vol", "expected_behavior": "range [-10000, 0]", "oracle_cases": 128},
            ],
        )
        partial = verify_reconstruction(
            ledger,
            {"DXBALL-OBL-001": {"passed_cases": 3205, "failed_cases": 0, "byte_or_behavior_match": True}},
        )
        self.assertEqual(partial["verdict"], "FAILED")
        self.assertEqual(len(partial["failed"]), 1)

        full = verify_reconstruction(
            ledger,
            {
                "DXBALL-OBL-001": {"passed_cases": 3205, "failed_cases": 0, "byte_or_behavior_match": True},
                "DXBALL-OBL-002": {"passed_cases": 128, "failed_cases": 0, "byte_or_behavior_match": True},
            },
        )
        self.assertEqual(full["verdict"], "PASS")
        self.assertEqual(full["verified_count"], 2)
        self.assertFalse(full["global_equivalence_claimed"])


if __name__ == "__main__":
    unittest.main()
