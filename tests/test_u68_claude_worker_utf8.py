"""U68: the Claude worker must report its envelope even when its own stdout is a cp949 pipe.

U67-C1 (2026-09-28) failed on Windows: the reviewer's answer held U+2014 (em dash), the worker printed its envelope
with `ensure_ascii=False`, and the cp949 stdout raised UnicodeEncodeError. The pilot then saw no envelope and recorded
UNKNOWN_EFFECT_NEEDS_RECONCILIATION although the paid call had already happened. The worker is started by path in a
child process, so the test runs it the same way with PYTHONIOENCODING=cp949 instead of calling main() in-process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKER = Path(__file__).resolve().parents[1] / "v7_harness" / "adapters" / "claude_worker.py"
# Characters seen in real answers: em dash (the U67-C1 case), a Korean word, and an emoji outside the BMP.
ANSWER = "done — 한글 \U0001F600"


class Cp949StdoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fake = self.root / "fake_claude.py"
        fake.write_text(textwrap.dedent(f"""
            import json, sys
            out = {{"result": {ANSWER!r}, "num_turns": 1, "total_cost_usd": 0.01,
                    "usage": {{"input_tokens": 3, "output_tokens": 2}}}}
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
        """), encoding="utf-8")
        self.env = {**os.environ, "CLAUDE_WORKER_CMD": json.dumps([sys.executable, str(fake)]),
                    "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(WORKER), "-p", "review", "--add-dir", str(self.root),
                               "--max-budget-usd", "0.10", "--print-timeout", "60s"],
                              env=self.env, capture_output=True, timeout=120)

    def test_non_cp949_answer_still_yields_one_envelope(self) -> None:
        done = self._run()
        self.assertEqual(0, done.returncode, done.stderr.decode("utf-8", errors="replace")[-400:])
        envelope = json.loads(done.stdout.decode("ascii"))
        self.assertEqual("SUCCESS", envelope["status"])
        self.assertEqual(ANSWER, envelope["response"])
        self.assertEqual(10_000, envelope["usage"]["cost_microusd"])

    def test_error_envelope_survives_cp949_too(self) -> None:
        self.env["CLAUDE_WORKER_CMD"] = json.dumps([sys.executable, "-c",
                                                    "import sys; sys.stderr.buffer.write('\\u2014 boom'.encode('utf-8')); sys.exit(3)"])
        done = self._run()
        envelope = json.loads(done.stdout.decode("ascii"))
        self.assertEqual("ERROR", envelope["status"])
        self.assertIn("— boom", envelope["error"])


if __name__ == "__main__":
    unittest.main()
