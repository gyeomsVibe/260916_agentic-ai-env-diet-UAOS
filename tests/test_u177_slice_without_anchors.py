"""U177: the local worker cuts a large file by itself, from what the manual already says.

Receipt (2026-10-10, ledger BLOCKED 20261010T1140-claude-0002): U176-L1 (dictation) and U176-C1 (a spec with twelve
backticked words) both ended PROMPT_TOO_LARGE with the model never called, on a 68 KB file. Slicing (U107) needed
hand-written backtick anchors and matched each on every line holding the word.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_u107_ollama_slice import LINES, TARGET_LINE, _big_file, _run
from v7_harness import manual
from v7_harness.adapters import ollama_worker as w

LIMIT = w.NUM_CTX - w.NUM_PREDICT
FAR_LINE = 100  # a second edit site far from TARGET_LINE (Antigravity audit relay_92656076, counterexample 1)


def _edit(search: str, replace: str, name: str = "pkg/big.py") -> str:
    return f"===EDIT: {name}===\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


class SliceWithoutAnchorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.big = _big_file(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_dictated_edit_on_a_big_file_reaches_the_model(self) -> None:
        task = "Copy the block exactly.\n\n" + _edit("def target_func():\n    return 1", "def target_func():\n    return 2")
        code, out, sent = _run(self.root, task, task.split("\n\n", 1)[1])
        self.assertEqual(1, len(sent), out)
        self.assertLessEqual(len(sent[0].encode("utf-8")) // 3, LIMIT)
        self.assertIn("def target_func():\n    return 1\n", sent[0].split("CURRENT CONTENTS:")[1])
        self.assertEqual((0, "SUCCESS"), (code, out["status"]), out)
        self.assertEqual("    return 2", self.big.read_text(encoding="utf-8").splitlines()[TARGET_LINE + 1])

    def test_every_search_block_of_a_file_is_shown(self) -> None:
        far = f"value_{FAR_LINE} = {FAR_LINE}  # padding that makes this file far larger than the local window"
        task = "Copy both blocks exactly.\n\n" + _edit(far, "value_far = 0") \
            + _edit("def target_func():\n    return 1", "def target_func():\n    return 2")
        _code, _out, sent = _run(self.root, task)
        self.assertEqual(1, len(sent))
        shown = sent[0].split("CURRENT CONTENTS:")[1]
        self.assertIn(far + "\n", shown)
        self.assertIn("def target_func():\n", shown)
        self.assertNotIn(f"value_{LINES // 2} = ", shown)  # lines between the two sites stay out

    def test_a_search_line_that_is_not_in_the_file_fails_before_the_call(self) -> None:
        task = "Copy the block exactly.\n\n" + _edit("def target_function():\n    return 1", "x = 1")
        code, out, sent = _run(self.root, task)
        self.assertEqual((1, []), (code, sent))
        self.assertTrue(out["error"].startswith("SEARCH_ANCHOR_NOT_FOUND:pkg/big.py:def target_function():"), out)

    def test_a_common_word_falls_back_to_the_line_that_defines_it(self) -> None:
        lines = self.big.read_text(encoding="utf-8").splitlines(keepends=True)
        for i in range(0, LINES, 4):  # the word is on 500 lines, so even 3 lines around each use overflow
            if i not in (TARGET_LINE, TARGET_LINE + 1):
                lines[i] = lines[i].rstrip("\n") + " target_func\n"
        self.big.write_text("".join(lines), encoding="utf-8")
        _code, _out, sent = _run(self.root, "Make `target_func` in `pkg/big.py` return 2.")
        self.assertEqual(1, len(sent))
        self.assertLessEqual(len(sent[0].encode("utf-8")) // 3, LIMIT)
        shown = sent[0].split("CURRENT CONTENTS:")[1]
        self.assertIn("def target_func():\n    return 1\n", shown)
        self.assertNotIn("value_8 = 8 ", shown)

    def test_definition_lines_of_other_file_types(self) -> None:
        pad = "".join(f"filler {i} mentions render_page in passing, far too often to show every use\n" for i in range(1500))
        for name, definition in (("doc/big.md", "## How render_page works\n"),
                                 ("web/big.ts", "export async function render_page(req: Request) {\n"),
                                 ("bin/big.sh", "render_page() {\n")):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(pad + definition + "UNIQUE_BODY_LINE\n" + pad, encoding="utf-8")
            shown = w.slice_text(name, path.read_text(encoding="utf-8"), ["render_page"], 3, definitions=True)
            self.assertIsNotNone(shown, name)
            self.assertIn("UNIQUE_BODY_LINE", shown, name)
            self.assertLess(len(shown.splitlines()), 20, name)
        self.assertIsNone(w.slice_text("data/big.csv", pad, ["render_page"], 3, definitions=True))

    def test_nothing_nameable_still_fails_and_says_what_to_write(self) -> None:
        code, out, sent = _run(self.root, "Tidy up `pkg/big.py`.")
        self.assertEqual((1, []), (code, sent))
        self.assertTrue(out["error"].startswith("PROMPT_TOO_LARGE: ~"), out)
        self.assertIn("backticks", out["error"])

    def test_lint_warns_before_a_run(self) -> None:
        contract = ("```contract\nwork_id: U177-T1\nworker: local\ngoal: tidy the big file\ninputs:\n- pkg/big.py sha256="
                    + "0" * 64 + "\nallow:\n- pkg/big.py\nacceptance: python -c \"pass\"\nforbidden: network\n"
                    "stop: two failures\njudge: codex\ntimeout_s: 60\n```\n\nTidy up `pkg/big.py`.\n")
        warnings = manual.lint(contract, self.root).warnings
        self.assertTrue(any(item.startswith("LOCAL_PROMPT_TOO_LARGE") for item in warnings), warnings)
        named = contract.replace("Tidy up `pkg/big.py`.", "Make `target_func` in `pkg/big.py` return 2.")
        warnings = manual.lint(named, self.root).warnings
        self.assertFalse(any(item.startswith("LOCAL_") for item in warnings), warnings)

    def test_preflight_never_reads_a_file_outside_the_workspace(self) -> None:
        # Codex REWORK relay_af81221a: preflight read `../outside.py` directly, past the admission the run uses.
        from unittest.mock import patch

        from v7_harness.context_admission import admit

        task = "Inspect `../outside.py`."
        self.assertEqual(["../outside.py"], admit(task, ["../outside.py"], self.root).escaped)
        with patch.object(Path, "is_file", return_value=True), \
                patch.object(Path, "read_text", return_value="def harmless_fixture():\n    pass\n") as read:
            self.assertEqual("", w.preflight(task, self.root))
        self.assertEqual(0, read.call_count)


if __name__ == "__main__":
    unittest.main()
