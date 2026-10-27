```contract
work_id: U262-L1
worker: local
goal: add pilot_dirs.live(project) that drops repo copies under .work unless their own ledger has an open attempt (slice 1 of U262)
inputs:
- v7_harness/pilot_dirs.py sha256=039846b3843f56e3d236ff3bad799956d176139a61273c3547520e525c217574
allow:
- v7_harness/pilot_dirs.py
context_allow:
- v7_harness/pilot_dirs.py
acceptance: python -c "import v7_harness.pilot_dirs as p; assert callable(p.live) and callable(p._repo_copy) and callable(p._has_open_attempt)"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/pilot_dirs.py. Make exactly two edits, shown as SEARCH/REPLACE blocks.

Edit 1 - import sqlite3:

SEARCH:
```python
from pathlib import Path
```
REPLACE:
```python
import sqlite3
from pathlib import Path

# U262: attempt states the broker has not settled (same set as sentinel._ledger_confirms_terminal_success).
_OPEN_STATES = ("PENDING", "RUNNING", "VERIFYING", "NEEDS_RECONCILIATION")
```

Edit 2 - add three new top-level functions after `discover`. Emit only these definitions, starting at column 0;
do not repeat any line of `discover`:

```python
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
```

Change nothing else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
