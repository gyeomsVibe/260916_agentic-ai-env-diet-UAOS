"""U47-O3: the test ledger guard leaves nothing in the system temp folder once the test process exits."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = (
    "import tests._env_guard as g\n"
    "g.SAFE_OLLA_USAGE.write_text('{}\\n', encoding='utf-8')\n"
    "import os\n"
    "assert os.environ['OLLA_USAGE'] == str(g.SAFE_OLLA_USAGE)\n"
    # U107-G: log_usage also makes `<log>.lock`; left behind it blocked U107-B-agy as EXTERNAL_WRITE (2026-10-01).
    "from v7_harness import olla\n"
    "olla.log_usage('test_guard')\n"
    "assert g.SAFE_OLLA_USAGE.with_suffix('.lock').exists()\n"
    "print(g.SAFE_OLLA_USAGE)\n"
)


class GuardCleanupTest(unittest.TestCase):
    def test_safe_ledger_is_removed_at_exit(self):
        done = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        path = Path(done.stdout.strip())
        self.assertTrue(path.name.startswith("uaos_test_olla_usage_"), path)
        self.assertFalse(path.exists(), f"left behind: {path}")
        self.assertFalse(path.with_suffix(".lock").exists(), f"left behind: {path.with_suffix('.lock')}")


if __name__ == "__main__":
    unittest.main()
