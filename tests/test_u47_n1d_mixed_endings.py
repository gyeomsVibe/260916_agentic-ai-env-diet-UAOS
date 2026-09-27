"""U47-N1d frozen acceptance (written by Claude): a file that mixes line endings is refused, never rewritten.

Codex's re-review of U47-N1c (2026-09-27) sent b"a\\r\\nb\\n": `_apply` picked CRLF for the whole file and returned
b"a\\r\\nb2\\r\\n", changing a line the edit never touched. The contract is now: one ending per file is kept byte for
byte (CRLF, LF or bare CR); a mixed file raises MIXED_LINE_ENDINGS and no file of the reply is written.
"""

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker

EDIT_B = "===EDIT: {name}===\n<<<<<<< SEARCH\nb\n=======\nb2\n>>>>>>> REPLACE\n"


class MixedEndingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_codex_counterexample_is_refused_and_bytes_kept(self):
        (self.ws / "m.txt").write_bytes(b"a\r\nb\n")
        with self.assertRaisesRegex(ValueError, "MIXED_LINE_ENDINGS:m.txt"):
            ollama_worker._apply(EDIT_B.format(name="m.txt"), self.ws)
        self.assertEqual(b"a\r\nb\n", (self.ws / "m.txt").read_bytes())

    def test_bare_cr_mixed_with_lf_is_refused(self):
        (self.ws / "m.txt").write_bytes(b"a\rb\n")
        with self.assertRaisesRegex(ValueError, "MIXED_LINE_ENDINGS"):
            ollama_worker._apply("===FILE: m.txt===\nz\n===END===\n", self.ws)
        self.assertEqual(b"a\rb\n", (self.ws / "m.txt").read_bytes())

    def test_refusal_writes_no_other_file_of_the_reply(self):
        (self.ws / "ok.txt").write_bytes(b"b\n")
        (self.ws / "m.txt").write_bytes(b"a\r\nb\n")
        with self.assertRaises(ValueError):
            ollama_worker._apply(EDIT_B.format(name="ok.txt") + EDIT_B.format(name="m.txt"), self.ws)
        self.assertEqual(b"b\n", (self.ws / "ok.txt").read_bytes())

    def test_single_ending_files_keep_their_bytes(self):
        for name, before, after in (("lf.txt", b"a\nb\n", b"a\nb2\n"), ("crlf.txt", b"a\r\nb\r\n", b"a\r\nb2\r\n"),
                                    ("cr.txt", b"a\rb\r", b"a\rb2\r")):
            (self.ws / name).write_bytes(before)
            self.assertEqual([name], ollama_worker._apply(EDIT_B.format(name=name), self.ws))
            self.assertEqual(after, (self.ws / name).read_bytes(), name)

    def test_new_file_and_file_without_breaks_get_lf(self):
        (self.ws / "one.txt").write_bytes(b"b")
        ollama_worker._apply("===FILE: one.txt===\nb\nc\n===END===\n===FILE: new.txt===\nx\ny\n===END===\n", self.ws)
        self.assertEqual(b"b\nc\n", (self.ws / "one.txt").read_bytes())
        self.assertEqual(b"x\ny\n", (self.ws / "new.txt").read_bytes())


if __name__ == "__main__":
    unittest.main()
