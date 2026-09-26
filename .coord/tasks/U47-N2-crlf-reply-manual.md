```contract
work_id: U47-N2
worker: apply
goal: Make the local worker's _apply accept a reply whose own lines end in CRLF instead of silently matching no block; add the frozen test.
inputs:
- v7_harness/adapters/ollama_worker.py sha256=54ded7b78a0f3e540dbfac61b8c4ccfed0216131e19040a81a211434a2e0d03d
allow:
- v7_harness/adapters/ollama_worker.py
- tests/test_u47_n2_crlf_reply.py
acceptance: python tests/u47_n2_check.py
forbidden: design changes; edits outside allow; editing or deleting other tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

===FILE: tests/test_u47_n2_crlf_reply.py===
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
===END===

===EDIT: v7_harness/adapters/ollama_worker.py===
<<<<<<< SEARCH
    written: list[str] = []
    pending: dict[Path, tuple[str, str]] = {}
=======
    # U47-N2: the block patterns expect "\n"; a reply whose own lines end in "\r\n" matched nothing and was dropped in
    # silence. Line endings of the written file are the target file's own (U47-N1), so normalising here loses nothing.
    text = text.replace("\r\n", "\n")
    written: list[str] = []
    pending: dict[Path, tuple[str, str]] = {}
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
