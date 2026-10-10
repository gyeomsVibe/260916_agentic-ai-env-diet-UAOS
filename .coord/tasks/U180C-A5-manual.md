```contract
work_id: U180C-A5
worker: apply
apply_after: U180C-L4
goal: U180C a coordinated project without a machine schedule reports WAIT/SCHEDULE_MISSING, not DONE
inputs:
- v7_harness/coord/next_card.py sha256=61de7705b18a9db7b85422c3823e5b9a4ceb26a20bb38b20a7ecc1369ebab287
- tests/test_u180c_schedule_boundary.py sha256=37757329ba45d3927cf73c87bf98ef3fedf73721b3071eddc236772602ab23db
allow:
- v7_harness/coord/next_card.py
context_allow:
- v7_harness/coord/next_card.py
acceptance: python -m unittest tests.test_u180c_schedule_boundary tests.test_u146a_next_card tests.test_u146a_r_ownership tests.test_u146a_r2_claim_lock
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Card U180C. Receipt: on 2026-10-10 the U180 order lived only in the PLAN file prose, so coord next answered from
the old schedule and every tool idled. A project that has a PLAN but no a machine schedule file must not read as
finished. Codex's local run U180C-L1 (Ollama author, bundle ee40ac69) made this change but has no recorded independent
review, so the commit gate refuses it; this is the same two added lines without its comment deletions. Dictation: copy
the one edit block below exactly and change nothing else.

===EDIT: v7_harness/coord/next_card.py===
<<<<<<< SEARCH
    if not path.is_file():
        return {"state": "DONE", "reason": "no schedule"}
=======
    if not path.is_file():
        if (path.parent / "PLAN.md").is_file():  # U180C: a plan without a machine schedule is unscheduled work
            return {"state": "WAIT", "code": "SCHEDULE_MISSING", "reason": "coordinated project has no schedule",
                    "action": "register authorized work in .coord/master_schedule.json before stopping"}
        return {"state": "DONE", "reason": "no schedule"}
>>>>>>> REPLACE

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
