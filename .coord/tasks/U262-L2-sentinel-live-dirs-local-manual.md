```contract
work_id: U262-L2
worker: local
goal: make sentinel.check_all_pilot_dirs read pilot_dirs.live instead of discover (slice 2 of U262)
inputs:
- v7_harness/coord/sentinel.py sha256=3e734de38a94e54489d03aceae2eab5f06f37065fae674d33f8e1007b2b6de10
allow:
- v7_harness/coord/sentinel.py
context_allow:
- v7_harness/coord/sentinel.py
acceptance: python -m unittest tests.test_u262_sentinel_skips_repo_copies tests.test_u47_sentinel_reconciliation
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/coord/sentinel.py. Make exactly one edit, shown as a SEARCH/REPLACE block.

Edit 1:

SEARCH:
```python
    from ..pilot_dirs import discover

    return sorted({task for pilot_dir in discover(project_root) for task in check_ledger_reconciliation(pilot_dir)})
```
REPLACE:
```python
    from ..pilot_dirs import live

    # U262: repo copies under .work/ carry historical summaries; only live pilot dirs raise NEEDS_RECONCILIATION.
    return sorted({task for pilot_dir in live(project_root) for task in check_ledger_reconciliation(pilot_dir)})
```

Change nothing else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
