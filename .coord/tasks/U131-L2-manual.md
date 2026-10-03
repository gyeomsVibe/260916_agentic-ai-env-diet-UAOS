```contract
work_id: U131-L2
worker: apply
goal: a recorded token count is a non-negative int, never a bool (U131-A audit)
inputs:
- .work/u131_apply2.md sha256=6f05fb1e1c27ccddc3c37c984544be50df6d43d5a7d862c041c124472516d2e2
allow:
- v7_harness/coord/windows.py
- v7_harness/coord/agy_dispatch.py
acceptance: python -m unittest tests.test_u131_agy_resume_cap tests.test_u127_agy_card_window tests.test_u120_agy_auto_reply tests.test_u114_windows tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u48_deliver tests.test_u49_dispatch_count
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: U131 exact apply 2 (U131-A audit): a token count is a non-negative int, never a bool

- Target files: `v7_harness/coord/agy_dispatch.py`, `v7_harness/coord/windows.py`

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
        if entry.get("id") and isinstance(tokens, int) and tokens < RESUME_MAX_INPUT:
=======
        if entry.get("id") and type(tokens) is int and 0 <= tokens < RESUME_MAX_INPUT:  # U131-A: bool is not a count
>>>>>>> REPLACE

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
    return str(envelope["conversation_id"]), tokens if isinstance(tokens, int) else None
=======
    return str(envelope["conversation_id"]), tokens if type(tokens) is int and tokens >= 0 else None
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
