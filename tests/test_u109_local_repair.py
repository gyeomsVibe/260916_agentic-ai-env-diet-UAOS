"""U109-R: one free local repair before a failed Ollama reply leaves the worker.

2026-10-01: U109-S looped on one line (`lines.insert(...)`) until the 4,096-token cap; U101-L1/L2 returned code with
a syntax error; U107-B used a shape the parser dropped. Each reply was thrown away whole, and the pilot's own retry
re-sent the same prompt with the same seed, which returns the same reply. The worker now tells the model what was
wrong and asks once more with another seed, still at 0 paid tokens.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from v7_harness.adapters import ollama_worker

GOOD = "===FILE: pkg/m.py===\nVALUE = 2\n"
LOOP = "===FILE: pkg/m.py===\nVALUE = 2\n" + "x.append(1)\n" * 40


class LocalRepairTests(unittest.TestCase):
    def _main(self, replies):
        calls = []

        def fake_generate(model, prompt, timeout_s, *, fmt=None, seed=None):
            calls.append((prompt, seed))
            return replies[len(calls) - 1], {"input_tokens": 100, "output_tokens": 10}

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pkg").mkdir()
            (root / "pkg" / "m.py").write_text("VALUE = 1\n", encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(ollama_worker, "_generate", fake_generate), \
                    mock.patch.object(ollama_worker, "_log"), redirect_stdout(out):
                code = ollama_worker.main(["-p", "Set VALUE to 2 in `pkg/m.py`.", "--add-dir", d])
            text = (root / "pkg" / "m.py").read_text(encoding="utf-8")
        return code, json.loads(out.getvalue()), calls, text

    def test_repeated_line_is_degenerate(self):
        self.assertTrue(ollama_worker.degenerate(LOOP))
        self.assertFalse(ollama_worker.degenerate(GOOD))
        self.assertFalse(ollama_worker.degenerate("a\n\n\n\n\n\n\n\n\n\nb\n"))  # blank lines are not a loop

    def test_a_looping_reply_gets_one_repair_with_another_seed(self):
        code, envelope, calls, text = self._main([LOOP, GOOD])
        self.assertEqual(0, code)
        self.assertEqual("SUCCESS", envelope["status"])
        self.assertEqual(2, len(calls))
        self.assertNotEqual(calls[0][1], calls[1][1])
        self.assertIn("repeated", calls[1][0])
        self.assertEqual("VALUE = 2\n", text)
        self.assertEqual(200, envelope["usage"]["input_tokens"])

    def test_an_unappliable_reply_is_repaired_with_its_error(self):
        bad = "===FILE: pkg/m.py===\nVALUE = (\n"
        code, envelope, calls, _text = self._main([bad, GOOD])
        self.assertEqual(0, code)
        self.assertIn("SYNTAX_ERROR", calls[1][0])
        self.assertIn("VALUE = (", calls[1][0])

    def test_repair_is_bounded_to_one(self):
        code, envelope, calls, text = self._main([LOOP, LOOP, GOOD])
        self.assertEqual(1, code)
        self.assertEqual("ERROR", envelope["status"])
        self.assertEqual(1 + ollama_worker.REPAIRS, len(calls))
        self.assertEqual("VALUE = 1\n", text)

    def test_a_good_first_reply_costs_one_call(self):
        code, _envelope, calls, _text = self._main([GOOD])
        self.assertEqual(0, code)
        self.assertEqual(1, len(calls))


if __name__ == "__main__":
    unittest.main()
