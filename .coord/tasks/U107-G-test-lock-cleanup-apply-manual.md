```contract
work_id: U107-G
worker: apply
goal: The test ledger guard also removes the .lock file log_usage leaves in TEMP, so paid pilot runs that run the tests stop failing as EXTERNAL_WRITE.
inputs:
- tests/_env_guard.py sha256=7693e6d24b7f94d3985b3c44ecb463764872ca5aa83501b6127509e3d957a304
- tests/test_u47_o3_guard_cleanup.py sha256=70f543a1c827ded24dcd5ecf16673242e4f3ca8fb588bb7f88d7816861391db7
allow:
- tests/_env_guard.py
acceptance: python -m unittest tests.test_u47_o3_guard_cleanup tests.test_000_env_guard
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly.

===EDIT: tests/_env_guard.py===
<<<<<<< SEARCH
    try:
        SAFE_OLLA_USAGE.unlink(missing_ok=True)
    except OSError:
        pass
=======
    # U107-G: log_usage also leaves `<log>.lock`; it blocked U107-B-agy as EXTERNAL_WRITE on 2026-10-01.
    for leftover in (SAFE_OLLA_USAGE, SAFE_OLLA_USAGE.with_suffix(".lock")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
