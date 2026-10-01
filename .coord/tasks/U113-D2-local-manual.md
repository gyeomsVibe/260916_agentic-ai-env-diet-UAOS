```contract
work_id: U113-D2
worker: local
goal: A LIMITED or ABSENT codex/claude target gets the mailbox only, no dispatch
inputs:
- v7_harness/coord/deliver.py sha256=ebb1552aab8d49b4bb8f9264fd5d5e2dee63d13e6e758b6e4400a155cefae19e
- tests/test_u113_desk_truth.py sha256=7a1fe3a2678849376adbd5d6cba49bf6144445346b5a313f859558ed74eac508
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u113_desk_truth.NoLetterWaitsInALimitedThread tests.test_u61_watcher_routes
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/coord/deliver.py with one exact SEARCH/REPLACE block inside the function `deliver`.

Find these lines in `deliver`:
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"

Keep them, and directly after them (same indentation as the line `if target is None:` above them, 4 spaces) add a new
block that does this: when requested_target is "codex" or "claude" and the presence state of that tool on desk is
"LIMITED" or "ABSENT", set target to None, so the letter is published to the mailbox only and nothing is dispatched.
Import read_presence locally inside the new block with the same import line the block above uses.
Put a two-line comment above the new block starting with "# U113:" that says: a relay queued into a LIMITED tool's
thread waits there and costs one paid turn per letter when it returns (7 relays piled up in Codex's thread on
2026-10-01); its hooks show the inbox instead (desk delta, U103).
Change nothing else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
