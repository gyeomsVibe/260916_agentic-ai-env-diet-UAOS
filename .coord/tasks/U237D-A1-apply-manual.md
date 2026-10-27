# U237-A1: native title adapter version bump (desk_title.py, one line)

Judge claude, deputy for LIMITED codex; Codex re-review owed. Card manual and fixed acceptance:
`.coord/tasks/U237-card-manual.md`. A top-level assignment cannot be spliced as a whole function (U236A-L2
SPLICE_UNSUPPORTED), so this one non-test line goes through `worker: apply` (U98-D: Python under 20 lines).

```contract
work_id: U237-A1
worker: apply
goal: every existing desk entry, BLOCKED ones included, gets one fresh native title budget under the U237 rules
inputs:
- v7_harness/coord/desk_title.py sha256=7aa2727ad54f2237aa555a77c9c293292dc333dc00d5a4a877d6fe161f125b1f
allow:
- v7_harness/coord/desk_title.py
acceptance: python -m unittest tests.test_u229_independent_title tests.test_u229_title_worker tests.test_u234_title_consensus
forbidden: editing or deleting tests; any other line; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; edits outside allow; no output; 600 seconds
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

===EDIT: v7_harness/coord/desk_title.py===
<<<<<<< SEARCH
ADAPTER_VERSION = "U229_NATIVE1"
=======
ADAPTER_VERSION = "U237_NATIVE2"  # U237: a new version resets every desk's native budget once (BLOCKED included)
>>>>>>> REPLACE
===END===

## Output

- Reply with ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
