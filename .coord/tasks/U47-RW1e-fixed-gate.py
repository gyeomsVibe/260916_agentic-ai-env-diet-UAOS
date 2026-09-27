"""Frozen U47-RW1e gate: static under pilot monitoring, targeted tests after pilot exit."""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


FROZEN = {
    "tests/test_u47_n1d_mixed_endings.py": "b2c6d563f895df3b8c0522402aedd05f668ad95cd7c720dd6c1e12b6f74a0e83",
    "tests/test_u47_a1b_presence_lease.py": "e55752fbd50de576f39def9b11a240e4b734fcf7e95ffa4860acf7599dd40700",
    "tests/test_u47_j6_codex_judge.py": "20c479b0e11382cf52cf460dc754aa927cf02577888f3c1427f0f96319537960",
    "tests/test_u47_rw1c_counterexamples.py": "95ae57227a470e309db26a537c6d79c26f2bad4d47730dd8a3045dd0f07ff295",
    "tests/test_u47_rw1d_counterexamples.py": "aadbfc0a4a95aacad650e8182499281d8895f9c07d5ff637043fc777cd226951",
    "tests/test_u47_j5_judge_budget.py": "46ad5fb588836b0ef4dc4276900f67179e5d5882a2efa9b9fc237af90cced73c",
    "v7_harness/adapters/ollama_worker.py": "58cf5371d6d3d0aaaeecabde5528843e578d33cbffd1031ef5c597ee66650e10",
    "v7_harness/cli.py": "e54bcdb43371fb0318de6ec9006d3f71cbccc187ffb7893f88517628c42dfba6",
    "v7_harness/coord/presence.py": "a51fa0d02beafffdfb9953005000f1e9e8d3489d9ccff04161d1f88e436e5538",
    "v7_harness/judge.py": "30fd80ee6a842e90603eea6356abfafe7982b5bba2344f9e926612db82ecdecb",
}

TARGETED = [
    "tests.test_000_env_guard",
    "tests.test_u47_n1d_mixed_endings",
    "tests.test_u47_a1b_presence_lease",
    "tests.test_u47_j6_codex_judge",
    "tests.test_u47_rw1c_counterexamples",
    "tests.test_u47_rw1d_counterexamples",
    "tests.test_u47_n1_newline_preserved",
    "tests.test_u47_n2_crlf_reply",
    "tests.test_u47_a1_agy_quota_presence",
    "tests.test_u46_pilot_judge",
    "tests.test_u47_j5_judge_budget",
    "tests.test_u45_conductor_succession",
    "tests.test_u32_sentinel_bell",
    "tests.test_u38_cost_gate_and_claude_worker",
    "tests.test_u16_local_worker",
    "tests.test_u21_calculator",
    "tests.test_u22_worker_limits",
    "tests.test_u34_precision_harness",
    "tests.test_u46_followup_fixes",
    "tests.test_u47_olla_record",
]


def static_gate() -> None:
    for name, expected in FROZEN.items():
        path = Path(name)
        if not path.is_file():
            raise SystemExit(f"FROZEN_FILE_MISSING {name}")
        normalized = path.read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(normalized).hexdigest()
        if actual != expected:
            raise SystemExit(f"FROZEN_FILE_CHANGED {name} {actual}")
        compile(normalized.decode("utf-8"), name, "exec")


parser = argparse.ArgumentParser()
parser.add_argument("--targeted", action="store_true")
args = parser.parse_args()
static_gate()
if args.targeted:
    raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", *TARGETED]))
print(f"STATIC_OK {len(FROZEN)}")
