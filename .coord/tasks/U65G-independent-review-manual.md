```contract
work_id: U65-G-REVIEW
worker: claude
goal: Independently judge whether the U65-G change gives canon-generated global rule files one writer without breaking bootstrap or uninstall behavior.
inputs:
- v7_harness/global_install.py sha256=d65f0566d2fb69239e2de6621354286fef68b6a06bba60e5857d97c136228ea3
- tests/test_u37_install_everywhere.py sha256=c4596292e05327d3b1e2f2c591c70c46f3a6a2207cc6617efb500ef7f0dd25f7
- docs/54_u65g-single-global-rules-owner.md sha256=bdd2e9d002cbd9095ce99482aa7e7e33e788964ef3e096ba6295e91f6b626fde
allow:
- v7_harness/global_install.py
- tests/test_u37_install_everywhere.py
- docs/54_u65g-single-global-rules-owner.md
acceptance: C:/Python314/python.exe -m unittest -v tests.test_u37_install_everywhere tests.test_u65_deploy_three_tools
forbidden: editing files; commit; push; merge; deploy; system settings; further delegation; trusting the author verdict
stop: input hash mismatch; ownership overlap; any P1; two failures with the same cause
judge: codex
timeout_s: 600
remote_budget_tokens: 8000
remote_budget_usd: 0.75
```

Read the hash-fixed diff. Challenge false-positive marker detection, uninstall ownership, bootstrap on unmanaged files, test fitting, and whether both generator Check and installer --check can become clean after a canon Apply. Run the fixed acceptance only if allowed. Return FACT / EVIDENCE / VERDICT / NEXT in English, under 1800 characters. Do not edit.
