"""U47-D1 fixed acceptance gate (written by Claude). The worker must create the frozen test verbatim and make it pass."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = "6ca22b42d0912cd888a6423ca82302667f1dac6598c8b47ca3d878050ee2aa4b"  # LF-normalized sha256 of the test

test = Path("tests/test_u47_d1_local_usage.py")
if not test.is_file():
    sys.exit("FROZEN_TEST_MISSING")
digest = hashlib.sha256(test.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
if digest != FROZEN:
    sys.exit(f"FROZEN_TEST_CHANGED {digest}")
# rsi.py and cli.py change: the rsi suites and the report/retention neighbours must stay green.
sys.exit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_000_env_guard", "tests.test_u47_d1_local_usage",
                          "tests.test_u36_evidence_gated_rsi", "tests.test_u42_r1_windows_wrapper",
                          "tests.test_u42_rsi_release", "tests.test_u47_retention_stages", "tests.test_u47_olla_record"]))
