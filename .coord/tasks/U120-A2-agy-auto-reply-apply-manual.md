```contract
work_id: U120-A2
worker: apply
goal: deliver hands a real delta for Antigravity to agy_dispatch.dispatch (U120); rerun of U120-A after the judge fixed an 8.3-path comparison in the acceptance test
inputs:
- v7_harness/coord/deliver.py sha256=6c38fa0f20ccb33fd78bfab49cda9296818508346df5f00ed7913eb31f8fb20f
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u120_agy_auto_reply tests.test_u118_agy_letter_unread tests.test_u117_watch_wakes_session tests.test_u115_card_window_route
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
                  "(headless, no user)") if _requires_wake(message) else ""
        return DeliverResult(False, "antigravity", "PUBLISHED", (), unread, message_id, digest)
=======
                  "(headless, no user)") if _requires_wake(message) else ""
        if unread and actor in ("claude", "codex") and os.environ.get("UAOS_AGY_AUTO", "1") != "0":
            # U120: a headless one-turn answer (U119 live: 27,989 tokens) is mailed back to the sender; a failure,
            # a loop tag or the daily cap keeps the U118 UNREAD route. UAOS_AGY_AUTO=0 opts out.
            from v7_harness.coord.agy_dispatch import dispatch
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run)
            detail = json.dumps(row, ensure_ascii=False)[:300] if row["state"] == "ANSWERED" else unread
            unread = f"AGY_{row['state']} {detail}"
        return DeliverResult(False, "antigravity", "PUBLISHED", (), unread, message_id, digest)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
