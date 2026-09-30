"""U102-W: a failed Ollama run keeps the model's raw reply, so the next manual fixes the real cause.

Receipt (2026-09-30): U101-L1 and U101-L2 both failed with SYNTAX_ERROR, and the run record kept `response: ""`.
The judge could not see why and added "no syntax errors" to the manual, which changed nothing. Only a local rerun
showed the cause: the model wrote the constants above `from __future__ import annotations`.
Fixed acceptance written by the judge (claude) before the fix.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.adapters import ollama_worker

# The U101-L2 failure shape: an assignment before the __future__ import is a SyntaxError.
BAD_REPLY = '===FILE: pkg/mod.py===\nX = 1\nfrom __future__ import annotations\n'
USAGE = {"input_tokens": 10, "output_tokens": 5}


class RawReplyTests(unittest.TestCase):
    def _run(self, reply: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pkg").mkdir()
            out = io.StringIO()
            with mock.patch.object(ollama_worker, "_generate", return_value=(reply, USAGE)), \
                    mock.patch.object(ollama_worker, "_log"), redirect_stdout(out):
                ollama_worker.main(["-p", "Create pkg/mod.py.", "--add-dir", tmp])
            return json.loads(out.getvalue().strip().splitlines()[-1])

    def test_syntax_error_keeps_raw_reply(self) -> None:
        envelope = self._run(BAD_REPLY)
        self.assertEqual("ERROR", envelope["status"])
        self.assertTrue(envelope["error"].startswith("SYNTAX_ERROR:pkg/mod.py"))
        self.assertEqual(BAD_REPLY, envelope["response"])

    def test_no_block_keeps_raw_reply(self) -> None:
        envelope = self._run("Sure, here is the code you asked for.")
        self.assertEqual("ERROR", envelope["status"])
        self.assertEqual("Sure, here is the code you asked for.", envelope["response"])


if __name__ == "__main__":
    unittest.main()
