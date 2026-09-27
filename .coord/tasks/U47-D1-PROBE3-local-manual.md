```contract
work_id: U47-D1-PROBE3
worker: local
goal: Replace one exact status line in sample.txt; no other change.
inputs:
- sample.txt sha256=89dcb80ee39f7ed2a93d4dbfce12c1e4cd6a7b12db121e628127602980540c16
- verify_probe.py sha256=f1d4840589a417fbb7b697a78b9f9ff9bf7432a170a139cacbdd0be707aac9c1
allow:
- sample.txt
acceptance: C:/Python314/python.exe verify_probe.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

# U47-D1-PROBE local calculator instructions

Work ID: `U47-D1-PROBE3`

Perform exactly one mechanical edit in `sample.txt`: replace the complete line `status=OLD` with `status=NEW`. Preserve `keep=unchanged` and the final newline byte-for-byte otherwise.

Return exactly one supported complete-file block:

```text
===FILE: sample.txt===
status=NEW
keep=unchanged
===END===
```

Allowed output is only the complete-file block above. Do not design, explain, approve, judge, delete, rename, create another file, read outside the supplied source, or make network/paid API calls.

Budget: paid API tokens `0`; local input cap `4096` tokens; local output cap `4096` tokens; wall-clock cap `300` seconds. Stop immediately if the exact line is absent or ambiguous. The independent judge is Claude (acting conductor while Codex is halted), using the fixed acceptance command and direct source/stage byte comparison. A worker `PASS` or exit code is not evidence.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
