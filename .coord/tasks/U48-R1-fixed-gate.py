"""Frozen U48-R1 gate (Claude, 2026-09-27): the R1 test file is hash-pinned, then R1 plus the U37 installer suite
(global_install.py changes, so its existing tests must still pass)."""

import hashlib
import subprocess
import sys
from pathlib import Path

FROZEN = {"tests/test_u48_r1_runtime_install.py": "d0402774103e1963a83c18fde42bbb27ff472a188fce576c1548fae1a8d5a3c8"}
for name, expected in FROZEN.items():
    data = Path(name).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"FROZEN_FILE_CHANGED {name}")
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", "tests.test_u48_r1_runtime_install",
                                  "tests.test_u37_install_everywhere"]))
