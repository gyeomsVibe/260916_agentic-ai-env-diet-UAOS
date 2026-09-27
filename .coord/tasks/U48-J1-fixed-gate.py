"""Frozen U48-J1 gate (Claude, 2026-09-27): frozen test hash, then Codex's fixed acceptance command plus the new
receipt test. Codex's command (U48-J1-codex-judgement-20260927.md) is run verbatim; the J1 test module is appended."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = {"tests/test_u48_j1_judge_receipt.py": "4b5d42068ea08e3c0512adaedb5020c732588d3594e05c3af588098f7dbea83d"}
for name, expected in FROZEN.items():
    data = Path(name).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"FROZEN_FILE_CHANGED {name}")
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_u46_pilot_judge",
                                  "tests.test_u47_j6_codex_judge", "tests.test_u47_rw1c_counterexamples",
                                  "tests.test_u48_j1_judge_receipt"]))
