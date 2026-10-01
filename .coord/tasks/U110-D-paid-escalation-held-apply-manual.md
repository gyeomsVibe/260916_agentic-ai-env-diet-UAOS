```contract
work_id: U110-D
worker: apply
goal: A failed local cascade stage with a budget is held for the judge unless the run names a paid worker with --escalate-to; no budget keeps the REMOTE_WITHOUT_MANUAL refusal
inputs:
- v7_harness/cli.py sha256=30051bc79625a870c8d377f1dbf054472ecb4393cf7e7317593f6f6b233e529e
- tests/test_u110_paid_escalation_held.py sha256=db6d286cb121ad3a16f49fb3904ec59c4beac10c770b4e89e942b668dbc88a21
- tests/test_u34_precision_harness.py sha256=f31944dbade536f951122a22f1177aa4dce89d1ccb4464ac9527dd8ca8dec8f6
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u110_paid_escalation_held tests.test_u38_cost_gate_and_claude_worker tests.test_u17_lane_worker tests.test_u21_calculator tests.test_u34_precision_harness tests.test_u106_local_first tests.test_u69_admission_gate
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
            escalate_to = getattr(args, "escalate_to", "agy")
            escalation = (_admission(source_dir, escalate_to, contract)
                          if escalate_to in REMOTE_WORKERS and remote_budget else None)
            if escalate_to in REMOTE_WORKERS and not remote_budget:
=======
            escalate_to = getattr(args, "escalate_to", None)
            escalation = (_admission(source_dir, escalate_to, contract)
                          if escalate_to in REMOTE_WORKERS and remote_budget else None)
            if escalate_to is None and remote_budget:
                # U110: paying is the judge's call on each run (--escalate-to); auto-escalation spent ~7.6M Antigravity
                # tokens on 9 runs (2026-09-30..10-01), most of them FAILED or blocked.
                summary["escalation"] = "HELD:FAILED_LOCAL_GOES_TO_THE_JUDGE"
                trace.append("held")
            elif escalate_to in REMOTE_WORKERS + (None,) and not remote_budget:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_pilot_run.add_argument("--escalate-to", choices=["agy", "lane", "claude"], default="agy", help="Worker for cascade second stage when local gets REWORK (default: agy)")
=======
    p_pilot_run.add_argument("--escalate-to", choices=["agy", "lane", "claude"], default=None, help="Worker for the cascade's second stage when local gets REWORK; omitted: hold for the judge (U110)")
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
