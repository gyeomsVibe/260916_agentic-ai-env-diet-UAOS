"""U124: Ollama copies dictated edits the way Antigravity used it (U23), and a copy that differs is never written.

Receipts (2026-10-02):
- U123-L and U123-L2 sent a 140-line `calculator_gate.py`, below EDIT_MODE_MIN_LINES=150, so the worker asked
  qwen2.5-coder:7b for the whole file and it dropped `_digest` and `parent_digests` both times (UNREQUESTED_DELETION,
  7,258 and 7,383 input tokens).
- U124-L: given two exact SEARCH/REPLACE blocks, the model re-emitted the whole `_apply` function in the fenced
  format, dropped 3 lines (the `_guard` call), changed one character, put the new function at end of file and skipped
  the second block. Its acceptance passed, so only a diff read by the judge caught it.
Antigravity's audits (relay_6aaf0fdb, relay_37ea8879) chose: find-and-replace for every existing .py file; a
deterministic dictation check; fail fast on a dictated SEARCH that does not apply or on FILE+EDIT for one path; no
fenced format while dictating. Fixed acceptance written by the judge (claude) before the run.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker as w
from v7_harness.adapters.ollama_worker import DICTATION_RULES, EDIT_RULES, FORMAT_RULES, _rules_for

ORIGINAL = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
EDIT_A = "===EDIT: m.py===\n<<<<<<< SEARCH\n    return 1\n=======\n    return 10\n>>>>>>> REPLACE\n"
EDIT_B = "===EDIT: m.py===\n<<<<<<< SEARCH\n    return 2\n=======\n    return 20\n>>>>>>> REPLACE\n"
TASK = f"Copy these edits exactly.\n\n{EDIT_A}\n{EDIT_B}"
EXPECTED = "def alpha():\n    return 10\n\n\ndef beta():\n    return 20\n"


class RulesForTest(unittest.TestCase):
    def test_short_existing_python_file_gets_edit_rules(self) -> None:
        self.assertIs(EDIT_RULES, _rules_for([("v7_harness/calculator_gate.py", "A = 1\n" * 140)]))

    def test_any_python_file_among_the_context_gets_edit_rules(self) -> None:
        named = [("docs/a.md", "x\n" * 5), ("v7_harness/x.py", "A = 1\n")]
        self.assertIs(EDIT_RULES, _rules_for(named))

    def test_short_non_python_file_keeps_whole_file_rules(self) -> None:
        self.assertIs(FORMAT_RULES, _rules_for([("docs/a.md", "x\n" * 10)]))

    def test_long_non_python_file_still_gets_edit_rules(self) -> None:
        self.assertIs(EDIT_RULES, _rules_for([("docs/a.md", "x\n" * 200)]))

    def test_no_context_keeps_whole_file_rules(self) -> None:
        self.assertIs(FORMAT_RULES, _rules_for([]))

    def test_dictated_task_gets_copy_rules_without_the_fenced_format(self) -> None:
        self.assertIs(DICTATION_RULES, _rules_for([("m.py", ORIGINAL)], TASK))
        self.assertNotIn("```", DICTATION_RULES)


class DictationCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "m.py").write_bytes(ORIGINAL.encode("utf-8"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _text(self) -> str:
        return (self.root / "m.py").read_bytes().decode("utf-8")

    def _refused(self, reply: str, task: str = TASK) -> str:
        with self.assertRaises(ValueError) as caught:
            w._apply(reply, self.root, task=task)
        self.assertEqual(ORIGINAL, self._text())  # nothing is written on a refused copy
        return str(caught.exception)

    def test_exact_copy_is_written(self) -> None:
        self.assertEqual(["m.py"], w._apply(f"{EDIT_A}\n{EDIT_B}", self.root, task=TASK))
        self.assertEqual(EXPECTED, self._text())

    def test_whole_file_copy_with_the_same_result_is_accepted(self) -> None:
        w._apply(f"===FILE: m.py===\n{EXPECTED}===END===\n", self.root, task=TASK)
        self.assertEqual(EXPECTED, self._text())

    def test_skipped_block_is_refused(self) -> None:
        self.assertTrue(self._refused(EDIT_A).startswith("DICTATION_MISMATCH:m.py:"))

    def test_changed_line_is_refused(self) -> None:
        wrong = EDIT_B.replace("return 20", "return 21")
        self.assertTrue(self._refused(f"{EDIT_A}\n{wrong}").startswith("DICTATION_MISMATCH:m.py:"))

    def test_fenced_rewrite_is_ignored_while_dictating(self) -> None:
        fenced = "===EDIT: m.py===\n```python\ndef alpha():\n    return 10\n\n\ndef beta():\n    return 20\n```\n"
        self.assertTrue(self._refused(fenced).startswith("DICTATION_MISMATCH"))

    def test_extra_path_is_refused(self) -> None:
        (self.root / "n.py").write_text("X = 1\n", encoding="utf-8")
        extra = "===EDIT: n.py===\n<<<<<<< SEARCH\nX = 1\n=======\nX = 2\n>>>>>>> REPLACE\n"
        self.assertTrue(self._refused(f"{EDIT_A}\n{EDIT_B}\n{extra}").startswith("DICTATION_MISMATCH"))
        self.assertEqual("X = 1\n", (self.root / "n.py").read_text(encoding="utf-8"))

    def test_dictation_that_does_not_apply_fails_fast(self) -> None:
        bad = EDIT_A.replace("return 1\n=", "return 99\n=")
        self.assertTrue(self._refused(bad, task=f"Copy.\n\n{bad}").startswith("DICTATION_EDIT_SEARCH_NOT_FOUND"))

    def test_file_and_edit_for_one_path_is_a_conflict(self) -> None:
        task = f"Copy.\n\n===FILE: m.py===\n{EXPECTED}===END===\n\n{EDIT_A}"
        self.assertTrue(self._refused(EDIT_A, task=task).startswith("DICTATION_BLOCK_CONFLICT:m.py"))

    def test_spec_task_without_dictation_is_unchanged(self) -> None:
        fenced = "===EDIT: m.py===\n```python\ndef alpha():\n    return 10\n```\n"
        self.assertEqual(["m.py"], w._apply(fenced, self.root, task="change `alpha` to return 10"))
        self.assertIn("return 10", self._text())


if __name__ == "__main__":
    unittest.main()
