```contract
work_id: U277-L1
worker: local
goal: stall._letter_waits honors structured verdict_requested flag
inputs:
- v7_harness/coord/stall.py sha256=e7a28d3a609683439429d09fa6fe6859892744135bc1b043a3cee88bf761a9a6
allow:
- v7_harness/coord/stall.py
context_allow:
- v7_harness/coord/stall.py
acceptance: python -m unittest tests.test_u179_wait_watchdog tests.test_u203_stall_quorum_timeout
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only `v7_harness/coord/stall.py`, function `_letter_waits`. Replace exactly these two lines:

```python
            if "VERDICT_REQUESTED=YES" not in str(payload.get("message", "")):
                continue
```

with:

```python
            # U277: the structured flag set by `deliver --verdict-requested` counts like the legacy wake word.
            if payload.get("verdict_requested") is not True \
                    and "VERDICT_REQUESTED=YES" not in str(payload.get("message", "")):
                continue
```

Change nothing else. Reply with a single ===EDIT block using SEARCH/REPLACE.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
