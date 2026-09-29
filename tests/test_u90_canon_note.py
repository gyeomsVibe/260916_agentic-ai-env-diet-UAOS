"""U90: the installer's notes no longer tell an agent to copy the portable block into the global-rules canon.

Seen 2026-09-29 on both post-merge `--check` runs (after v6.0.0 and after U88): the note still said to put
uaos_global_rule_block.md into the canon "or its next Apply removes the block". Since canon v6.0.0 the canon carries
UAOS-RSI itself in core.md and its adapters, so following the note would duplicate the rules and break its size cap.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from v7_harness.global_install import NOTES, plan

ROOT = Path(__file__).resolve().parents[1]


class CanonNoteTests(unittest.TestCase):
    def test_notes_point_to_the_canon_sources_not_to_the_block(self) -> None:
        text = " ".join(NOTES)
        self.assertNotIn("into that canon", text)
        self.assertIn("core.md", text)

    def test_a_plain_home_change_does_not_ask_for_the_canon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".claude").mkdir()
            for change in plan(home, "python", repo=ROOT):
                self.assertNotIn("add the block to the canon", change.detail, change.target)


if __name__ == "__main__":
    unittest.main()
