```contract
work_id: U98-D-F1-A2
worker: apply
goal: Refuse `pilot run --worker apply` without a manual when its prompt dictates more than 20 code lines, and give the two new delegation constants their reasons.
inputs:
- v7_harness/delegation.py sha256=dd4c6591914335a033dd9fb4d9e82d9bb87bf1f44062caf8afe9e2efb8fb1531
- v7_harness/cli.py sha256=1102c90d3427ff67b1ac2ff13738b3a0c593a5eb2799dd7815e78a6273b1cf52
allow:
- v7_harness/delegation.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u98d_f1_bypass tests.test_u98d_delegate_first tests.test_u34_precision_harness tests.test_u38_cost_gate_and_claude_worker tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; editing or weakening tests; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. Ollama wrote the delegation fixes (U98-D-F1-L2, APPLIED). This follow-up does two things. It adds the one P1 that lives in `cli.py`: with no manual, lint never ran. It also adds the two reason comments that Ollama left out.

===EDIT: v7_harness/delegation.py===
<<<<<<< SEARCH
CODE_SUFFIXES = (
=======
# Code a shell or runtime executes; a dictated script is dictated code too (U98-D-R P1).
CODE_SUFFIXES = (
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/delegation.py===
<<<<<<< SEARCH
FAILED_OUTCOMES = frozenset(
=======
# Outcomes that mean the delegate really failed; APPROVE, PASS or no outcome never unlock apply (U98-D-R P1).
FAILED_OUTCOMES = frozenset(
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                          "message": "paid workers (agy, claude) need --manual with remote_budget_tokens"},
                         indent=2, ensure_ascii=False))
        return 2
=======
                          "message": "paid workers (agy, claude) need --manual with remote_budget_tokens"},
                         indent=2, ensure_ascii=False))
        return 2
    # U98-D-F1: without a manual lint never ran, so apply took any amount of dictated code (U98-D-R P1).
    if chosen == "apply" and contract is None:
        from .delegation import delegate_first_errors

        refusal = delegate_first_errors(prompt or "", {"worker": "apply"}, source_dir)
        if refusal:
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "DELEGATE_FIRST",
                              "verdict_hint": "BLOCKED", "manual_errors": refusal}, indent=2, ensure_ascii=False))
            return 2
>>>>>>> REPLACE
===END===
