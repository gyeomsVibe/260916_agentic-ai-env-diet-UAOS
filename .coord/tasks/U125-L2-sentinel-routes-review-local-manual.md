```contract
work_id: U125-L2
worker: local
goal: The sentinel sends each RSI review to the acting conductor (U125 part 2, dictated)
inputs:
- v7_harness/coord/sentinel.py sha256=9e1bcb6a67917c72502f20b087e2dd04a51b73fce19a2557e5180071444d6a7d
allow:
- v7_harness/coord/sentinel.py
acceptance: python -m unittest tests.test_u125_rsi_review_wakes_conductor tests.test_u36_evidence_gated_rsi tests.test_u116_superseded_family tests.test_u23_mailbox tests.test_u32_sentinel_bell tests.test_u47_sentinel_reconciliation tests.test_u88_p1_superseded
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: the sentinel sends each RSI review to the acting conductor (U125, part 2)

- Target file: `v7_harness/coord/sentinel.py`
- Anchor: `run_sentinel_cycle`

Copy the one edit block below into the file exactly, in this same SEARCH/REPLACE format.
Do not rewrite whole functions. Change nothing else.

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        policy = load_policy(project_root)
        for message_id, payload in rsi_review_messages(project_root, analyze(load_rows(project_root), policy), policy):
=======
        from .presence import conductor, read_all

        policy = load_policy(project_root)
        # U125: the review goes to whoever conducts now; an UNKNOWN desk keeps it mailbox-only (fail closed).
        lead = conductor(read_all(project_root))["conductor"]
        target = lead if lead in ("codex", "claude", "antigravity") else None
        analysis = analyze(load_rows(project_root), policy)
        for message_id, payload in rsi_review_messages(project_root, analysis, policy, target=target):
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
