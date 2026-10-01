"""U107-B: the local model gets the parts of a big file the task names, instead of failing before it starts.

Receipt: U106-A2 cascade, 2026-10-01. The Ollama step returned `PROMPT_TOO_LARGE: ~27k tokens > 12288` without calling
the model, because ollama_worker pastes every named file whole; the run escalated to Antigravity and spent 921,850 paid
tokens. 윤겸스: "올라마 메뉴얼 명세서를 올라마 특성에 맞게 조율하여 최적화하는 것도 3대 도구 공통로직". A 7B model with a
16k window edits by exact SEARCH/REPLACE blocks, so it only needs exact copies of the lines around what the task names.
Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.adapters import ollama_worker as w

LINES = 2000
TARGET_LINE = 1200  # 0-based index of `def target_func` inside the big file


def _big_file(root: Path) -> Path:
    path = root / "pkg" / "big.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"value_{i} = {i}  # padding that makes this file far larger than the local window\n" for i in range(LINES)]
    lines[TARGET_LINE] = "def target_func():\n"
    lines[TARGET_LINE + 1] = "    return 1\n"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _run(root: Path, task: str, reply: str = "no blocks") -> tuple[int, dict, list[str]]:
    sent: list[str] = []

    def fake_generate(model: str, prompt: str, timeout_s: int, **_kw):
        sent.append(prompt)
        return reply, {"input_tokens": 1, "output_tokens": 1}

    out = io.StringIO()
    # U109: these tests measure the first prompt only; the one free repair call has its own tests (test_u109_local_repair).
    with mock.patch.object(w, "_generate", fake_generate), mock.patch.object(w, "_log"), \
            mock.patch.object(w, "REPAIRS", 0, create=True), \
            mock.patch("v7_harness.adapters.gpu_priority.pilot_holds", lambda _t: contextlib.nullcontext()), \
            contextlib.redirect_stdout(out):
        code = w.main(["-p", task, "--add-dir", str(root)])
    return code, json.loads(out.getvalue()), sent


class SliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.big = _big_file(self.root)
        # The whole file alone is over the window: without slicing this is the U106-A2 failure.
        self.assertGreater(len(self.big.read_bytes()) // 3, w.NUM_CTX - w.NUM_PREDICT)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_big_file_reaches_the_model_as_the_named_window(self) -> None:
        _code, _out, sent = _run(self.root, "Make `target_func` in `pkg/big.py` return 2.")
        self.assertEqual(1, len(sent))
        prompt = sent[0]
        self.assertLessEqual(len(prompt.encode("utf-8")) // 3, w.NUM_CTX - w.NUM_PREDICT)
        self.assertIn("def target_func():\n    return 1\n", prompt)
        self.assertIn(f"value_{TARGET_LINE - 5} = {TARGET_LINE - 5}", prompt)  # context around the anchor
        self.assertNotIn("value_10 = 10 ", prompt)  # far lines stay out
        self.assertIn("omitted", prompt)  # the model is told the copy is partial
        self.assertIn("<<<<<<< SEARCH", prompt)  # a partial copy must never be rewritten whole

    def test_an_edit_copied_from_the_window_applies_to_the_whole_file(self) -> None:
        reply = ("===EDIT: pkg/big.py===\n<<<<<<< SEARCH\ndef target_func():\n    return 1\n=======\n"
                 "def target_func():\n    return 2\n>>>>>>> REPLACE\n")
        code, out, _sent = _run(self.root, "Make `target_func` in `pkg/big.py` return 2.", reply)
        self.assertEqual((0, "SUCCESS"), (code, out["status"]), out)
        lines = self.big.read_text(encoding="utf-8").splitlines()
        self.assertEqual((LINES, "    return 2"), (len(lines), lines[TARGET_LINE + 1]))

    def test_a_big_file_with_nothing_named_still_fails_before_the_call(self) -> None:
        code, out, sent = _run(self.root, "Tidy up `pkg/big.py`.")
        self.assertEqual((1, []), (code, sent))
        self.assertTrue(out["error"].startswith("PROMPT_TOO_LARGE"), out)

    def test_a_small_named_file_still_goes_whole(self) -> None:
        small = self.root / "pkg" / "small.py"
        small.write_text("def helper():\n    return 0\n\nLAST = 'tail line'\n", encoding="utf-8")
        _code, _out, sent = _run(self.root, "Make `target_func` in `pkg/big.py` return `helper` from `pkg/small.py`.")
        self.assertEqual(1, len(sent))
        self.assertIn("LAST = 'tail line'", sent[0])
        self.assertIn("def target_func():", sent[0])

    def test_a_file_that_fits_is_never_cut(self) -> None:
        small = self.root / "pkg" / "fits.py"
        small.write_text("".join(f"line_{i} = {i}\n" for i in range(300)), encoding="utf-8")
        _code, _out, sent = _run(self.root, "Change `line_150` in `pkg/fits.py` to 0.")
        self.assertEqual(1, len(sent))
        self.assertIn("line_0 = 0\n", sent[0])
        self.assertIn("line_299 = 299\n", sent[0])
        self.assertNotIn("omitted", sent[0])


if __name__ == "__main__":
    unittest.main()
