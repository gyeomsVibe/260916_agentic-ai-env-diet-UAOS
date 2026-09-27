"""Frozen U48-D0 gate (Claude, 2026-09-27): the D0 test file is hash-pinned, then the deliver suite must pass 50 of
50 repeats (Codex handoff: ">=50/50 eight-process repeats"; the previous guard measured 48/50), then the mailbox
suites once, because mailbox.publish changes."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = {"tests/test_u48_deliver.py": "54fa2c074065a7fc077e7a8677bdb2bd16341e275954761cdf6f56dbe5fceea6"}
REPEATS = 50  # the acceptance bar Codex set for the eight-process tests
for name, expected in FROZEN.items():
    data = Path(name).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"FROZEN_FILE_CHANGED {name}")
failed = 0
for run in range(REPEATS):
    code = subprocess.call([sys.executable, "-m", "unittest", "-q", "tests.test_u48_deliver"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failed += code != 0
print(f"deliver repeats: {REPEATS - failed}/{REPEATS} OK")
if failed:
    raise SystemExit(1)
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_u23_mailbox",
                                  "tests.test_u32_mailbox_lossless", "tests.test_u32_sentinel_bell",
                                  "tests.test_u15_coord_cli", "tests.test_cli", "tests.test_u36_evidence_gated_rsi",
                                  "tests.test_u38_cost_gate_and_claude_worker"]))
