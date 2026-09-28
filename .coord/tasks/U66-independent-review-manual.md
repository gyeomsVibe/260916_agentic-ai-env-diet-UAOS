```contract
work_id: U66-REVIEW
worker: claude
goal: Independently review the U66 pending-marker fix for the publish-to-accepted double-wake race and return a verdict without editing files.
inputs:
- v7_harness/coord/deliver.py sha256=aada355dca62ecdd5fcca0f6b07a6d3d7da953d235f517934a63e7ced2a2c82a
- v7_harness/coord/watch.py sha256=7eb50c9488483ac83ad8177502b24c5f0266cd396db049c58fd03b97b71d8c6e
- tests/test_u64f_no_double_wake.py sha256=8069a6e931b2aac94836550b7cec7003216b9b59b89c98228dabfd1b9fd30219
- docs/53_u66-atomic-dispatch-intent.md sha256=363bdd403f94d1f6010d11572c51326b4aca6b139496385117617f108c12cf41
allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/watch.py
- tests/test_u64f_no_double_wake.py
- docs/53_u66-atomic-dispatch-intent.md
acceptance: C:/Python314/python.exe -m unittest -v tests.test_u64f_no_double_wake tests.test_u64_nonstop_dispatch tests.test_u48_deliver tests.test_u61_watcher_routes tests.test_u59_shared_desk
forbidden: editing any file; commit; push; merge; deploy; model delegation; trusting author claims without reading diff and tests
stop: input hash mismatch; ownership overlap; any P1; two failures with the same cause
judge: codex
timeout_s: 600
remote_budget_tokens: 12000
remote_budget_usd: 1.00
```

Read the four hash-fixed inputs and the git diff. Check concurrency, idempotence, failure fallback, stale pending behavior, target routing, test fitting, and preservation of publish-before-guard. Run only the fixed acceptance command. Return FACT / EVIDENCE / VERDICT / NEXT in English. Do not edit.
