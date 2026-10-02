```contract
work_id: U122-F1R
worker: local
goal: sentinel loop survives a failed heartbeat write (U122-F1, Antigravity audit P1)
inputs:
- v7_harness/cli.py sha256=87cb80ede8fc045eb2155ae223c94e19875728b452749c0d4bd660ab3270c594
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u122_f1_heartbeat_write_failure tests.test_u122_sentinel_stale_pid tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Task: in v7_harness/cli.py, inside the resident loop that calls `_execute_once`, move the heartbeat line

    pid_file.write_text(str(os.getpid()), encoding="utf-8")  # U122: each cycle refreshes the heartbeat

from before the try statement to the first line inside the try block, directly above the call to `_execute_once`, so a
PermissionError from the write is caught by the existing except clause and reported like any bad cycle.
Keep the comment line "# A resident operator must outlive one bad cycle ..." directly above the try statement.
Change nothing else.

Current code (lines 1333-1341):

        while True:
            pid_file.write_text(str(os.getpid()), encoding="utf-8")  # U122: each cycle refreshes the heartbeat
            # A resident operator must outlive one bad cycle (locked file, corrupt line); it reports and goes on.
            try:
                res = _execute_once()
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            _report(res)
            time.sleep(args.interval)

Reply with one ===EDIT: v7_harness/cli.py=== block using <<<<<<< SEARCH / ======= / >>>>>>> REPLACE / ===END===.
The SEARCH text must be copied exactly from the current code above, with the same indentation.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
