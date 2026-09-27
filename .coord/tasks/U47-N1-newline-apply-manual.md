```contract
work_id: U47-N1c
worker: apply
goal: Make the local worker's _apply keep each file's existing line endings byte-for-byte (new files LF) and add the frozen test.
inputs:
- v7_harness/adapters/ollama_worker.py sha256=643543f7a8c9b869a025ce29fda8a4752490b259834b043e66937785e641940f
allow:
- v7_harness/adapters/ollama_worker.py
- tests/test_u47_n1_newline_preserved.py
acceptance: python tests/u47_n1_check.py
forbidden: design changes; edits outside allow; editing or deleting other tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

===FILE: tests/test_u47_n1_newline_preserved.py===
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
===END===

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    for target, (_rel, content) in pending.items():
        target.write_text(content, encoding="utf-8")
    return written
=======
    for target, (_rel, content) in pending.items():
        # U47-N1: write_text turned every "\n" into "\r\n" on Windows, so an LF file came back CRLF and exact-byte
        # acceptance failed on a correct edit. Keep the line ending the file already uses; a new file gets LF.
        eol = "\r\n" if target.is_file() and b"\r\n" in target.read_bytes() else "\n"
        target.write_bytes(content.replace("\r\n", "\n").replace("\n", eol).encode("utf-8"))
    return written
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
