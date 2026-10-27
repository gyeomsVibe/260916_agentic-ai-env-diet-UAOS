"""U184, U185-S1, U186: the judge-frozen acceptance scripts run unchanged against this checkout.

`tests/fixed_gates/` holds byte copies of the scripts the three cards were accepted on. They were kept outside the
repository, so no CI run guarded the fixes. Each script takes its source root from argv and imports the code under
test at import time, so each runs in its own process.
"""
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / "tests" / "fixed_gates"
NEXT_CARD = ROOT / "v7_harness" / "coord" / "next_card.py"
# sha256 of each script with LF line endings: a checkout may convert line endings, the text must not change.
FROZEN = {
    "U184_stall_accept.py": "0b4998996057572db5e61d97f8ee29ae4f4ab7cdb80a93eeae5e5039a943d0db",
    "U185_session_accept.py": "f7032e7a14a6125a7bc349ee0e341db4ec3837b6cfcabd626a49bd6e567e88df",
    "U185_session_extra_accept.py": "52ab9530bddeae1cefe772ffabcee79c277b7c6b28fa5059470f01334ce0d87a",
    "U186_window_accept.py": "42663dbb0d972e50fb6d81ef4f8312f45feecb363651fd1556513a2538be3b22",
    "U186_window_stress.py": "794bde0d866c4641943ea33de87ef7e19af9ec5436dc62ee1183656a9c49dba7",
}
# The slowest script (60 rounds of 16 threads) ended in under 10 s on the judge's PC; 300 s only bounds a hang.
TIMEOUT_S = 300


def run(script: str, *arguments) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATES / script), *map(str, arguments)], cwd=GATES, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)


class FixedGates(unittest.TestCase):
    def passes(self, script: str, *arguments) -> None:
        done = run(script, *arguments)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-4000:])

    def test_the_scripts_are_the_frozen_text(self):
        for name, expected in FROZEN.items():
            with self.subTest(script=name):
                text = (GATES / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(text).hexdigest(), expected)

    def test_u184_stall_keeps_terminal_safety_and_scope_phases(self):
        self.passes("U184_stall_accept.py", ROOT)

    def test_u185_assigned_session_frozen_five(self):
        self.passes("U185_session_accept.py", NEXT_CARD, ROOT)

    def test_u185_assigned_session_additional_refusals(self):
        self.passes("U185_session_extra_accept.py", NEXT_CARD, ROOT)

    def test_u186_window_claim_fixed_four(self):
        self.passes("U186_window_accept.py", ROOT)

    def test_u186_window_claim_sixty_rounds_of_sixteen_threads(self):
        self.passes("U186_window_stress.py", ROOT)


if __name__ == "__main__":
    unittest.main()
