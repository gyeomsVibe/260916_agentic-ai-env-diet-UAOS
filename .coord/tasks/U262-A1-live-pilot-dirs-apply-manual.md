```contract
work_id: U262-A1
worker: apply
goal: the reconciliation sentinel reads only live pilot dirs, so repo copies under .work/ stop raising NEEDS_RECONCILIATION P01.
apply_after: U262-L1
inputs:
- v7_harness/pilot_dirs.py sha256=039846b3843f56e3d236ff3bad799956d176139a61273c3547520e525c217574
- v7_harness/coord/sentinel.py sha256=3e734de38a94e54489d03aceae2eab5f06f37065fae674d33f8e1007b2b6de10
- tests/test_u262_sentinel_skips_repo_copies.py sha256=59bb3bb688584361ee75e89bc1c0b428b4a83702e45c7de106931ca270a94bee
allow:
- v7_harness/pilot_dirs.py
- v7_harness/coord/sentinel.py
acceptance: python -m unittest tests.test_u262_sentinel_skips_repo_copies tests.test_u47_sentinel_reconciliation tests.test_u260_schedule_superseded tests.test_u261_reconcile_orphan_summary
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. Ollama U262-L1 failed PROMPT_TOO_LARGE (attempt 1, no context_allow) and
SPLICE_SYNTAX:1 (attempt 2, indented anchor line); attempt 3 SUCCEEDED its callable-only acceptance but dropped the
`_OPEN_STATES` constant, so `_has_open_attempt` raises NameError. Its three functions are kept verbatim; the
judge-written constant and the sentinel caller are applied directly (U98-D apply_after).

===EDIT: v7_harness/pilot_dirs.py===
<<<<<<< SEARCH
from pathlib import Path
=======
import sqlite3
from pathlib import Path

# U262: attempt states the broker has not settled (same set as sentinel._ledger_confirms_terminal_success).
_OPEN_STATES = ("PENDING", "RUNNING", "VERIFYING", "NEEDS_RECONCILIATION")
>>>>>>> REPLACE

===EDIT: v7_harness/pilot_dirs.py===
<<<<<<< SEARCH
    return [directory for directory in candidates if (directory / "runs").is_dir()]
=======
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
>>>>>>> REPLACE

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
    from ..pilot_dirs import discover

    return sorted({task for pilot_dir in discover(project_root) for task in check_ledger_reconciliation(pilot_dir)})
=======
    from ..pilot_dirs import live

    # U262: repo copies under .work/ carry historical summaries; only live pilot dirs raise NEEDS_RECONCILIATION.
    return sorted({task for pilot_dir in live(project_root) for task in check_ledger_reconciliation(pilot_dir)})
>>>>>>> REPLACE

Change nothing else.
