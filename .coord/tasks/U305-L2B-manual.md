```contract
work_id: U305-L2B
worker: local
goal: In v7_harness/rsi.py, add SPLICE_UNSUPPORTED and SPLICE_SYNTAX keys to REMEDIES so `_cause` classifies historical PROVIDER_ERROR rows accurately.
inputs:
- v7_harness/rsi.py sha256=72e63263778e64eff1b40027f18a6145adcef60f1d11eff5942a54d1663505c4
allow:
- v7_harness/rsi.py
acceptance: C:\Python314\python.exe -m unittest tests/test_u305_ollama_failure_class.py -k test_rsi_cause_maps_historical_provider_error_rows
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

In `v7_harness/rsi.py`, inside the `REMEDIES` dict, right after the `"DICTATION_MISMATCH"` entry and before `"PROVIDER_ERROR"`, add two entries:
- `"SPLICE_UNSUPPORTED": ("manual_template", "Re-cut into one ===EDIT slice of about 20 lines and rerun worker: local; use worker: apply with apply_after only after a small slice failed twice"),`
- `"SPLICE_SYNTAX": ("manual_template", "Re-cut into one ===EDIT slice of about 20 lines and rerun worker: local; use worker: apply with apply_after only after a small slice failed twice"),`
Keep all existing entries in `REMEDIES` unchanged.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
