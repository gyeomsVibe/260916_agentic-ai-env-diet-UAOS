"""U47-N2 fixed acceptance gate (written by Claude). The worker must create the frozen test verbatim and make it pass."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = "37ce312e6208c319eac0aef189f02a88bd3f4a87b85c5712fb6ff4c8ff047570"  # LF-normalized sha256 of the test

test = Path("tests/test_u47_n2_crlf_reply.py")
if not test.is_file():
    sys.exit("FROZEN_TEST_MISSING")
digest = hashlib.sha256(test.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
if digest != FROZEN:
    sys.exit(f"FROZEN_TEST_CHANGED {digest}")
sys.exit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_000_env_guard", "tests.test_u47_n2_crlf_reply",
                          "tests.test_u47_n1_newline_preserved", "tests.test_u16_local_worker",
                          "tests.test_u21_calculator", "tests.test_u22_worker_limits",
                          "tests.test_u34_precision_harness", "tests.test_u46_followup_fixes",
                          "tests.test_u47_olla_record"]))
