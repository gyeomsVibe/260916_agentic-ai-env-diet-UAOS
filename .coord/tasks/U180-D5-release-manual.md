```contract
work_id: U180-D5-REL-L1
worker: local
goal: In v7_harness/judge.py line 326, inside the approval pilot command list, replace the argument  "--worker", author,  with  "--worker", "local" if author == "ollama" else author,  . Change nothing else.
inputs:
- v7_harness/judge.py sha256=11eed2db5a4683ddb807e166e37f7353048062698130aa88ebdc3cbdeda419e6
allow:
- v7_harness/judge.py
acceptance: python -m unittest tests.test_u180_d5_approval_worker
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

- Change only the files under `allow`. Keep every other line byte-identical.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
