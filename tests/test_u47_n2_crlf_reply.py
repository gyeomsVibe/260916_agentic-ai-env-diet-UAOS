"""U47-N2 frozen acceptance (written by Claude): a reply whose own lines end in CRLF is still applied.

The U47-N1c red-team (2026-09-27) sent `===FILE: f.txt===\\r\\n...===END===\\r\\n`: the block patterns expect "\\n", so
`_apply` matched nothing and returned without writing or failing, leaving the file unchanged in silence.
"""

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker


class CrlfReplyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_crlf_file_block_is_applied_in_the_file_ending(self):
        (self.ws / "f.txt").write_bytes(b"x\ny\n")
        written = ollama_worker._apply("===FILE: f.txt===\r\nx2\r\ny\r\n===END===\r\n", self.ws)
        self.assertEqual(["f.txt"], written)
        self.assertEqual(b"x2\ny\n", (self.ws / "f.txt").read_bytes())

    def test_crlf_edit_block_is_applied(self):
        (self.ws / "a.txt").write_bytes(b"x=1\r\ny=2\r\n")
        reply = "===EDIT: a.txt===\r\n<<<<<<< SEARCH\r\nx=1\r\n=======\r\nx=9\r\n>>>>>>> REPLACE\r\n"
        self.assertEqual(["a.txt"], ollama_worker._apply(reply, self.ws))
        self.assertEqual(b"x=9\r\ny=2\r\n", (self.ws / "a.txt").read_bytes())


if __name__ == "__main__":
    unittest.main()
