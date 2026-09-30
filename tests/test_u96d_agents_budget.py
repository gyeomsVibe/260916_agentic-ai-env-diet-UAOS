"""U96-D: the project AGENTS.md leaves Codex at least 2 KiB of instruction budget.

Receipt (U95-R audit, 2026-09-30): Codex reads the global `~/.codex/AGENTS.md` (14,207 B) and this file (18,403 B)
under a 32 KiB budget, leaving 158 B. Whether the global file counts toward `project_doc_max_bytes` is UNKNOWN (the
docs do not say), so the check assumes it does: the safe side.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODEX_BUDGET = 32 * 1024  # Codex's documented default instruction budget (project_doc_max_bytes)
MARGIN = 2 * 1024  # room for one more rule paragraph before Codex silently truncates the tail
GLOBAL_BYTES = 14_236  # canon v7.1.1 dist/codex/AGENTS.md; raise with the canon, never to pass this check


class AgentsBudgetTests(unittest.TestCase):
    def test_project_agents_leaves_codex_margin(self) -> None:
        size = len((ROOT / "AGENTS.md").read_bytes())
        self.assertLessEqual(size, CODEX_BUDGET - MARGIN - GLOBAL_BYTES,
                             f"AGENTS.md is {size} B; trim it instead of raising the numbers")


if __name__ == "__main__":
    unittest.main()
