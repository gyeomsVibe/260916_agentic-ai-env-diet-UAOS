"""U47-A1 fixed acceptance gate (written by Claude). The worker must create the frozen test verbatim and make it pass."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = "e3356744aea9ce58c0dc905f8c6ea3453b7ffc651c533dcd8038258fcb0903cd"  # LF-normalized sha256 of the test

test = Path("tests/test_u47_a1_agy_quota_presence.py")
if not test.is_file():
    sys.exit("FROZEN_TEST_MISSING")
digest = hashlib.sha256(test.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
if digest != FROZEN:
    sys.exit(f"FROZEN_TEST_CHANGED {digest}")
# judge.py changes: the judge suites and the presence/route suites must stay green.
sys.exit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_000_env_guard",
                          "tests.test_u47_a1_agy_quota_presence", "tests.test_u46_pilot_judge",
                          "tests.test_u47_j5_judge_budget", "tests.test_u45_general_uaos"]))
