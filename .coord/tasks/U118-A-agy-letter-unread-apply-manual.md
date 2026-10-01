```contract
work_id: U118-A
worker: apply
goal: coord deliver to antigravity: a real delta says UNREAD and names pilot review --reviewer agy
inputs:
- v7_harness/coord/deliver.py sha256=6b6880d2e15ebc8702180b578602abe5b6cb425e6a5cdab578a2cacc5033886b
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u118_agy_letter_unread tests.test_u117_watch_wakes_session tests.test_u115_card_window_route
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
        # U95-A: no CLI wakes Antigravity; its PreInvocation hook names the letter on its next turn (agy_line).
        return DeliverResult(False, "antigravity", "PUBLISHED", (), "", message_id, digest)
=======
        # U95-A: no CLI wakes Antigravity; its PreInvocation hook names the letter on its next turn (agy_line).
        # U118: a real delta stays unread until a user turn there; say so and name the headless route (user report).
        unread = ("UNREAD until a user turn in Antigravity; for a verdict run `pilot review --reviewer agy` "
                  "(headless, no user)") if _requires_wake(message) else ""
        return DeliverResult(False, "antigravity", "PUBLISHED", (), unread, message_id, digest)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
