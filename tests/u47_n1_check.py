"""U47-N1 fixed acceptance gate (written by Claude). The worker must create the frozen test verbatim and make it pass."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = "a4a52811a7d01cf3b5992950cd79ac029211a64fbb9ee9de70f3c7bac74d9cd7"  # LF-normalized sha256 of the test

test = Path("tests/test_u47_n1_newline_preserved.py")
if not test.is_file():
    sys.exit("FROZEN_TEST_MISSING")
digest = hashlib.sha256(test.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
if digest != FROZEN:
    sys.exit(f"FROZEN_TEST_CHANGED {digest}")
sys.exit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_000_env_guard", "tests.test_u47_n1_newline_preserved",
                          "tests.test_u16_local_worker", "tests.test_u21_calculator", "tests.test_u22_worker_limits",
                          "tests.test_u34_precision_harness", "tests.test_u46_followup_fixes"]))
