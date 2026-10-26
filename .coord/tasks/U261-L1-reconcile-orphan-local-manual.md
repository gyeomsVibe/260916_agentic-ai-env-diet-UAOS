```contract
work_id: U261-L1
worker: local
goal: pilot reconcile clears a failed summary with no open attempt so the NEEDS_RECONCILIATION P1 alert can end
inputs:
- v7_harness/pilot.py sha256=5e8d7037133b7e0a136787cfc444d0b6b98f87af4387c6bf97359c751dc44b3f
- tests/test_u261_reconcile_orphan_summary.py sha256=f83679e7c5f00d44edecb34f703bb0d4be8bb7613b96c74fb7c05111639f2ed6
allow:
- v7_harness/pilot.py
acceptance: python -m unittest tests.test_u261_reconcile_orphan_summary tests.test_u47_sentinel_reconciliation
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/pilot.py. Make exactly three edits, shown as SEARCH/REPLACE blocks.

Edit 1 - add a helper directly before `def reconcile_pilot(`:

SEARCH:
```python
def reconcile_pilot(*, work_dir: Path, task_id: str) -> dict[str, Any]:
```
REPLACE:
```python
def _abandon_orphan_summary(work_dir: Path, task_id: str) -> dict[str, Any]:
    """U261: a failed summary with no open attempt (refused before the ledger row, e.g. SOURCE_DIVERGED) is abandoned.

    Before this, reconcile answered NOTHING_TO_RECONCILE and the sentinel's NEEDS_RECONCILIATION alert never cleared.
    """
    from v7_harness.coord.sentinel import needs_reconciliation

    summary_path = work_dir / "runs" / task_id / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = None
    if not isinstance(summary, dict) or not needs_reconciliation(summary):
        return {"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0}
    summary.update({"abandoned_from_error_class": summary.get("error_class"), "state": "ABANDONED",
                    "error_class": "ABANDONED", "promotion": "BLOCKED", "acceptance_exit": None,
                    "verdict_hint": "BLOCKED"})
    _write_summary(summary_path, summary)
    return {"state": "ABANDONED", "reconciled_attempts": 0}


def reconcile_pilot(*, work_dir: Path, task_id: str) -> dict[str, Any]:
```

Edit 2 - the first early return (no database):

SEARCH:
```python
    if not db_path.exists():
        return {"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0}
```
REPLACE:
```python
    if not db_path.exists():
        return _abandon_orphan_summary(work_dir, task_id)
```

Edit 3 - the second early return (no open attempt):

SEARCH:
```python
            if not target_attempts:
                return {"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0}
```
REPLACE:
```python
            if not target_attempts:
                return _abandon_orphan_summary(work_dir, task_id)
```

`json`, `Path`, `Any` and `_write_summary` already exist in the module. Change nothing else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
