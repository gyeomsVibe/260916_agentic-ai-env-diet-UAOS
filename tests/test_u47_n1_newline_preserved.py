"""U47-N1 frozen acceptance (written by Claude): the local worker keeps each file's line endings byte-for-byte.

U47-D1-PROBE2 (2026-09-27) wrote the right text into an LF `sample.txt` as CRLF bytes, because `_apply` used
`Path.write_text`, which turns every "\n" into "\r\n" on Windows. An exact-byte acceptance then failed on a correct
edit. `_apply` must write an existing file in the line ending it already uses and a new file with LF.
"""

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker


class NewlinePreservedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_file_block_keeps_lf(self):
        (self.ws / "sample.txt").write_bytes(b"status=OLD\nkeep=unchanged\n")
        ollama_worker._apply("===FILE: sample.txt===\nstatus=NEW\nkeep=unchanged\n===END===\n", self.ws)
        self.assertEqual(b"status=NEW\nkeep=unchanged\n", (self.ws / "sample.txt").read_bytes())

    def test_file_block_keeps_crlf(self):
        (self.ws / "sample.txt").write_bytes(b"status=OLD\r\nkeep=unchanged\r\n")
        ollama_worker._apply("===FILE: sample.txt===\nstatus=NEW\nkeep=unchanged\n===END===\n", self.ws)
        self.assertEqual(b"status=NEW\r\nkeep=unchanged\r\n", (self.ws / "sample.txt").read_bytes())

    def test_edit_block_keeps_lf(self):
        (self.ws / "a.txt").write_bytes(b"x=1\ny=2\n")
        ollama_worker._apply("===EDIT: a.txt===\n<<<<<<< SEARCH\nx=1\n=======\nx=9\n>>>>>>> REPLACE\n", self.ws)
        self.assertEqual(b"x=9\ny=2\n", (self.ws / "a.txt").read_bytes())

    def test_edit_block_keeps_crlf(self):
        (self.ws / "a.txt").write_bytes(b"x=1\r\ny=2\r\n")
        ollama_worker._apply("===EDIT: a.txt===\n<<<<<<< SEARCH\nx=1\n=======\nx=9\n>>>>>>> REPLACE\n", self.ws)
        self.assertEqual(b"x=9\r\ny=2\r\n", (self.ws / "a.txt").read_bytes())

    def test_new_file_is_lf(self):
        ollama_worker._apply("===FILE: new.txt===\na\nb\n===END===\n", self.ws)
        self.assertEqual(b"a\nb\n", (self.ws / "new.txt").read_bytes())


if __name__ == "__main__":
    unittest.main()
