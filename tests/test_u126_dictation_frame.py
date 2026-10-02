"""U126: a dictation reply that drops the ===EDIT/SEARCH frame but copies the REPLACE text exactly is the copy.

Receipts (2026-10-02):
- U125-L2 and U125-L2R dictated one SEARCH/REPLACE block for `v7_harness/coord/sentinel.py`. Both times
  qwen2.5-coder:7b replied with only the REPLACE text, fenced and under a `===FILE / <path>===` header (242 output
  tokens), so the worker failed with "model returned no file block" and the card fell back to `worker: apply`.
- A 0-token probe with the dictation alone (363 input tokens, no file context) gave the same frameless reply; its
  lines were the REPLACE text exactly.
The dictation check (U124) still decides: only lines equal to the dictated REPLACE texts, in order, are accepted.
Fixed acceptance written by the judge (claude) before the run.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker as w

ORIGINAL = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
EDIT_A = "===EDIT: m.py===\n<<<<<<< SEARCH\n    return 1\n=======\n    x = 1\n\n    return x * 10\n>>>>>>> REPLACE\n"
EDIT_B = "===EDIT: m.py===\n<<<<<<< SEARCH\n    return 2\n=======\n    return 20\n>>>>>>> REPLACE\n"
ONE = f"Copy this edit exactly.\n\n{EDIT_A}"
TWO = f"Copy these edits exactly.\n\n{EDIT_A}\n{EDIT_B}"
AFTER_ONE = "def alpha():\n    x = 1\n\n    return x * 10\n\n\ndef beta():\n    return 2\n"
AFTER_TWO = "def alpha():\n    x = 1\n\n    return x * 10\n\n\ndef beta():\n    return 20\n"
NO_BLOCK = "model returned no file block"


class FramelessDictationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "m.py").write_bytes(ORIGINAL.encode("utf-8"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _text(self) -> str:
        return (self.root / "m.py").read_bytes().decode("utf-8")

    def _refused(self, reply: str, task: str) -> str:
        written, error = w._try_apply(reply, self.root, task)
        self.assertEqual([], written)
        self.assertEqual(ORIGINAL, self._text())
        return error

    def test_recorded_frameless_reply_is_the_copy(self) -> None:
        reply = "===FILE / m.py===\n```python\n    x = 1\n\n    return x * 10\n```"  # the U125-L2R shape
        self.assertEqual((["m.py"], ""), w._try_apply(reply, self.root, ONE))
        self.assertEqual(AFTER_ONE, self._text())

    def test_bare_replace_text_is_the_copy(self) -> None:
        self.assertEqual((["m.py"], ""), w._try_apply("    x = 1\n\n    return x * 10\n", self.root, ONE))
        self.assertEqual(AFTER_ONE, self._text())

    def test_two_blocks_in_order_are_the_copy(self) -> None:
        reply = "```python\n    x = 1\n\n    return x * 10\n```\n\n```python\n    return 20\n```\n"
        self.assertEqual((["m.py"], ""), w._try_apply(reply, self.root, TWO))
        self.assertEqual(AFTER_TWO, self._text())

    def test_written_text_is_the_dictation_not_the_reply(self) -> None:
        # Dissent from relay_d4b85c66 (agy REVISE: dropped blank lines could corrupt a multiline string): the reply is
        # only compared; the file receives the dictated blocks, so its blank lines come from the dictation.
        self.assertEqual((["m.py"], ""), w._try_apply("    x = 1\n    return x * 10\n", self.root, ONE))
        self.assertEqual(AFTER_ONE, self._text())

    def test_changed_line_is_refused(self) -> None:
        self.assertEqual(NO_BLOCK, self._refused("    x = 2\n\n    return x * 10\n", ONE))

    def test_missing_line_is_refused(self) -> None:
        self.assertEqual(NO_BLOCK, self._refused("    return x * 10\n", ONE))

    def test_changed_indentation_is_refused(self) -> None:
        self.assertEqual(NO_BLOCK, self._refused("x = 1\n\nreturn x * 10\n", ONE))

    def test_blocks_out_of_order_are_refused(self) -> None:
        self.assertEqual(NO_BLOCK, self._refused("    return 20\n    x = 1\n\n    return x * 10\n", TWO))

    def test_extra_text_is_refused(self) -> None:
        self.assertEqual(NO_BLOCK, self._refused("Here is the edit:\n    x = 1\n\n    return x * 10\n", ONE))

    def test_spec_task_still_needs_a_block(self) -> None:
        self.assertEqual(NO_BLOCK, self._refused("    x = 1\n\n    return x * 10\n", "make `alpha` return 10"))

    def test_dictated_whole_file_is_not_reframed(self) -> None:
        task = f"Copy.\n\n===FILE: m.py===\n{AFTER_TWO}===END===\n"
        self.assertEqual(NO_BLOCK, self._refused(AFTER_TWO, task))


if __name__ == "__main__":
    unittest.main()
