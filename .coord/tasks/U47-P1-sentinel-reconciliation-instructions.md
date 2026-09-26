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
