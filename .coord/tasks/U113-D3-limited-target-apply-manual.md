```contract
work_id: U113-D3
worker: apply
goal: A LIMITED or ABSENT codex/claude target gets the mailbox only, no dispatch
inputs:
- v7_harness/coord/deliver.py sha256=ebb1552aab8d49b4bb8f9264fd5d5e2dee63d13e6e758b6e4400a155cefae19e
- tests/test_u113_desk_truth.py sha256=7a1fe3a2678849376adbd5d6cba49bf6144445346b5a313f859558ed74eac508
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u113_desk_truth.NoLetterWaitsInALimitedThread tests.test_u61_watcher_routes tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_u49_dispatch_count tests.test_u49_guard_release_race tests.test_u53_nonstop_relay tests.test_u53_turn_lock_delete_pending
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly. (Ollama run U113-D2 put the same block after the function's return path, where it never runs.)

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
=======
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
    # U113: a relay queued into a LIMITED tool's thread waits there and costs one paid turn per letter when it returns
    # (7 relays piled up in Codex's thread on 2026-10-01); its hooks show the inbox instead (desk delta, U103).
    elif target in ("codex", "claude"):
        from v7_harness.coord.presence import read as read_presence
        if read_presence(desk, target)["state"] in ("LIMITED", "ABSENT"):
            target = None
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
