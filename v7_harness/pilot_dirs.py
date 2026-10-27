"""Where pilot runs live.

`pilot run --work-dir` is free-form: `.coord/pilot` (AGENTS.md), `.work/pilot_P08` (P08) or `.coord` (the CLI
default). Readers that looked only at `.coord/pilot` missed real runs, so they look at every candidate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# U262: attempt states the broker has not settled (same set as sentinel._ledger_confirms_terminal_success).
_OPEN_STATES = ("PENDING", "RUNNING", "VERIFYING", "NEEDS_RECONCILIATION")


def discover(project: Path) -> list[Path]:
    project = Path(project)
    candidates = [project / ".coord" / "pilot", project / ".coord"]
    work = project / ".work"
    if work.is_dir():
        children = sorted(child for child in work.iterdir() if child.is_dir())
        candidates += children
        # U210: work dirs also nest one level deeper, `.work/<a>/<b>` (e.g. .work/u210/run6).
        candidates += sorted(nested for child in children for nested in child.iterdir() if nested.is_dir())
    return [directory for directory in candidates if (directory / "runs").is_dir()]


def _repo_copy(root: Path) -> bool:
    """A git checkout (`.git` dir or worktree file) or a project copy (`.coord/PLAN.md`) parked under `.work/`."""
    return (root / ".git").exists() or (root / ".coord" / "PLAN.md").is_file()


def _has_open_attempt(directory: Path) -> bool:
    db_path = directory / "coord.sqlite3"
    if not db_path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            marks = ",".join("?" * len(_OPEN_STATES))
            row = connection.execute(f"SELECT 1 FROM attempts WHERE state IN ({marks}) LIMIT 1", _OPEN_STATES).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return True  # an unreadable ledger stays visible rather than hidden
    return row is not None


def live(project: Path) -> list[Path]:
    """U262: pilot dirs whose state is this project's to reconcile.

    `.work/` also holds ~90 repo copies (`.work/wt_u257`, `.work/u75`) carrying the git-tracked historical
    `.coord/runs/P01/summary.json`; they are other checkouts, so they count only while their own ledger is open.
    """
    project = Path(project)
    work = project / ".work"

    def copy_only(directory: Path) -> bool:
        try:
            first = directory.relative_to(work).parts[0]
        except (ValueError, IndexError):
            return False
        return _repo_copy(work / first) and not _has_open_attempt(directory)

    return [directory for directory in discover(project) if not copy_only(directory)]
