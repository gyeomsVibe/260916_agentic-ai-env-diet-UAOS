```contract
work_id: U277-A1
worker: apply
goal: stall._letter_waits honors the structured verdict_requested flag (U277 S2)
inputs:
- v7_harness/coord/stall.py sha256=e7a28d3a609683439429d09fa6fe6859892744135bc1b043a3cee88bf761a9a6
allow:
- v7_harness/coord/stall.py
acceptance: python -m unittest tests.test_u179_wait_watchdog tests.test_u203_stall_quorum_timeout
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
apply_after: U277-L1
```

## Instructions for the worker

Apply the block below exactly. Ollama slice U277-L1 failed SPLICE_UNSUPPORTED (second same-cause SPLICE failure today after U275-R8-L1), so this is the escalation.

===EDIT: v7_harness/coord/stall.py===
<<<<<<< SEARCH
            if "VERDICT_REQUESTED=YES" not in str(payload.get("message", "")):
                continue
=======
            # U277: the structured flag set by `deliver --verdict-requested` counts like the legacy wake word.
            if payload.get("verdict_requested") is not True                     and "VERDICT_REQUESTED=YES" not in str(payload.get("message", "")):
                continue
>>>>>>> REPLACE
===END===

## Output

- Reply with ===EDIT blocks only.
