"""U93: files that UAOS hooks rewrite every session are ignored and untracked in this repository too.

Seen three times by 2026-09-29: the U91 sentinel ran a stale desk, Codex's install check reported drift 5 from that
desk, and the desk sat 166 commits behind main. Cause: `.coord/codex_brief.md` (written by `coord presence --say brief`)
and `.coord/usage/runs.jsonl` (appended by the usage ledger) were tracked here, although the installer writes both into
every other project's .gitignore (`UAOS_GITIGNORE_LINES`) and docs/36 says the ledger is never committed. A hook write
left the desk dirty, and any main commit touching the same file blocked the desk's fast-forward.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from v7_harness.cli import UAOS_GITIGNORE_LINES

ROOT = Path(__file__).resolve().parents[1]
# The two hook-written files from the receipt; each must stay in the installer list this repo mirrors.
HOOK_WRITTEN = (".coord/codex_brief.md", ".coord/usage/runs.jsonl")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8")


class RuntimeFilesUntrackedTests(unittest.TestCase):
    def test_every_installer_ignore_line_is_in_this_repo_gitignore(self) -> None:
        lines = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
        self.assertEqual([entry for entry in UAOS_GITIGNORE_LINES if entry not in lines], [])

    def test_hook_written_files_are_not_tracked(self) -> None:
        self.assertTrue(set(HOOK_WRITTEN) <= set(UAOS_GITIGNORE_LINES))
        result = _git("ls-files", "--", *HOOK_WRITTEN)
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertEqual(result.stdout.split(), [])


if __name__ == "__main__":
    unittest.main()
