```contract
work_id: U99-L-A1
worker: apply
goal: Skip client-generated synthetic assistant rows in v7_harness/output_lint.py so the S3 baseline counts only Claude text.
inputs:
- v7_harness/output_lint.py sha256=0cabd712e6cf59ac46266f39e4154d397e288e02c676816819d22999d60f1e78
- tests/test_u99l_output_lint.py sha256=146ba1c72a41fef335e67b79b0e380a5cfcb11c0e40fb59269b0524c6c39063a
allow:
- v7_harness/output_lint.py
acceptance: python -m unittest tests.test_u99l_output_lint
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly. Ollama wrote `v7_harness/output_lint.py` (U99-L2, APPLIED). The first baseline run counted the client's own "session limit" notice as Claude's English text; those rows carry model `<synthetic>` or `isApiErrorMessage`. This skips them.

===EDIT: v7_harness/output_lint.py===
<<<<<<< SEARCH
            if not isinstance(row, dict) or row.get("type") != "assistant":
                continue
=======
            if not isinstance(row, dict) or row.get("type") != "assistant":
                continue
            # The client stores its own notices (usage limit, API error) as assistant rows; they are not Claude's words.
            if row.get("isApiErrorMessage") or (row.get("message") or {}).get("model") == "<synthetic>":
                continue
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
