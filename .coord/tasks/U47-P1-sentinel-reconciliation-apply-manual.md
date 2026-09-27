```contract
work_id: U47-P1
worker: apply
goal: Suppress stale reconciliation alerts only when the pilot SQLite ledger confirms a successful attempt and no attempt remains PENDING, RUNNING, VERIFYING, or NEEDS_RECONCILIATION; keep missing, invalid, empty, nonterminal, and summary-only cases fail-closed.
inputs:
- v7_harness/coord/sentinel.py sha256=62c7b7bc8813d4c8f3e9e5bd9266b2ab8befda7117ad2130991499de4b762ee1
- tests/test_u47_sentinel_reconciliation.py sha256=a7996eebc9c7cfb94943501a76b243e628994ce326e17c33037cb0a7f4b2aa26
allow:
- v7_harness/coord/sentinel.py
- tests/test_u47_sentinel_reconciliation.py
acceptance: python -m unittest tests.test_u47_sentinel_reconciliation tests.test_u32_sentinel_bell tests.test_u23_mailbox && python -m unittest discover -s tests -p "test_*.py"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 1800
remote_budget_tokens: 0
```

## Instructions for the worker

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
import json
import os
import sys
=======
import json
import os
import sqlite3
import sys
>>>>>>> REPLACE

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
def check_ledger_reconciliation(pilot_dir: Path) -> list[str]:
    runs_dir = pilot_dir / "runs"
    if not runs_dir.is_dir():
        return []

    needs_reconcile = []
    for item in runs_dir.iterdir():
        if item.is_dir():
            summary_file = item / "summary.json"
            if summary_file.is_file():
                try:
                    data = json.loads(summary_file.read_text(encoding="utf-8"))
                except Exception:
                    needs_reconcile.append(item.name)
                    continue
                if not isinstance(data, dict) or needs_reconciliation(data):
                    needs_reconcile.append(item.name)
    return sorted(needs_reconcile)
=======
def _ledger_confirms_terminal_success(pilot_dir: Path, task_id: str) -> bool:
    """Return true only when a readable ledger has success and no attempt still needs reconciliation."""
    db_path = pilot_dir / "coord.sqlite3"
    if not db_path.is_file():
        return False
    connection = None
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        states = [row[0] for row in connection.execute(
            "SELECT state FROM attempts WHERE task_id=?", (task_id,)
        ).fetchall()]
    except (OSError, sqlite3.Error):
        return False
    finally:
        if connection is not None:
            connection.close()
    unresolved = {"PENDING", "RUNNING", "VERIFYING", "NEEDS_RECONCILIATION"}
    return "SUCCEEDED" in states and not unresolved.intersection(states)


def check_ledger_reconciliation(pilot_dir: Path) -> list[str]:
    runs_dir = pilot_dir / "runs"
    if not runs_dir.is_dir():
        return []

    needs_reconcile = []
    for item in runs_dir.iterdir():
        if item.is_dir():
            summary_file = item / "summary.json"
            if summary_file.is_file():
                try:
                    data = json.loads(summary_file.read_text(encoding="utf-8"))
                except Exception:
                    needs_reconcile.append(item.name)
                    continue
                if not isinstance(data, dict):
                    needs_reconcile.append(item.name)
                elif needs_reconciliation(data) and not _ledger_confirms_terminal_success(pilot_dir, item.name):
                    needs_reconcile.append(item.name)
    return sorted(needs_reconcile)
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
