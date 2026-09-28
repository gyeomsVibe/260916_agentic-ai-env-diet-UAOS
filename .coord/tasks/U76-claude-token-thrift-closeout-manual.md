```contract
work_id: U76-A
worker: claude
goal: Implement the smallest deterministic controlled-pair token-savings report, then stop for Codex evidence judgment; do not claim savings without matched pairs.
inputs:
- .coord/PLAN.md sha256=a001cad72667e67c1ecc3673f27131ae5422b7a4d8f9032fbf821d03ef1b7deb
- .coord/tasks/U56-thrift-mode-20260927.md sha256=4bf825a6f49b51310e5837eecc6ce6394a3e26cc1ac09a47c79af18b88bc848d
- docs/62_u74-ledger-closure-and-review.md sha256=3e5d7f910f6fda393ad6a811aa76a75b79274b6ebe29702c4f131298ca38b189
- v7_harness/coord/usage_ledger.py sha256=ab252db1c359af7752cacbbc4810f0226eba1222fd833abf857c33e121c12812
- v7_harness/coord/thrift.py sha256=e832fbaad81aa173cd6ded8f6ae8ab62c50af00ca64ed0688a90b2a64a3e7dba
- v7_harness/rsi.py sha256=a927d7824baf18ab95b2eb31e3e959ccd7cc97d257e48bb701cef1e6025b6d2b
- tests/test_u27_usage_ledger.py sha256=ac4f53a1065c05925f23a28d2e1e72c4f82ad1a8e95d914849ef2bfdfc8204d3
- tests/test_u36_evidence_gated_rsi.py sha256=4619af168d609d7e93ffb1ff29d95a97982921068bab4768c698b2ef58015f63
- tests/test_u63_thrift_mode.py sha256=099baecea5f92ba53f740dfa16c78c277da8f928b401f697296f69b72ab13ffd
allow:
- v7_harness/coord/token_savings.py
- v7_harness/cli.py
- tests/test_u76_token_savings.py
- docs/63_u76-token-thrift-closeout-design.md
- .coord/PLAN.md
acceptance: C:/Python314/python.exe -m unittest -v tests.test_u27_usage_ledger tests.test_u36_evidence_gated_rsi tests.test_u63_thrift_mode tests.test_u73_session_usage tests.test_u74_closure tests.test_u76_token_savings
forbidden: remote push; merge; deploy; deletion; system settings; credentials or permissions; recursive paid worker call; Antigravity call while LIMITED; changing existing acceptance tests; inventing a baseline; fixed time decay; claiming MEASURED with fewer than 10 valid pairs; editing outside allow; further delegation
stop: input hash mismatch; another owner already implements U76-A; any P1; source divergence; acceptance change; three failures with the same cause; scope requires a human approval boundary
judge: codex
timeout_s: 1200
remote_budget_tokens: 120000
remote_budget_usd: 0.50
```

# Project manual transmitted with the contract

- work_id: U76
- goal: finish UAOS token thrift with evidence, not self-report.
- authority: Codex ACTIVE owns plan, order, and final verdict; Claude is deputy and single writer only for the assigned card; Antigravity acts only if succession rules select it.
- ledger: `.coord/PLAN.md` is canonical. Check the mailbox and ledger for duplicate ownership before writing.
- continuity: ACK_ONLY, unchanged state, liveness, and empty output never wake a paid model. ACTIONABLE_DELTA, a failed gate, P1, or an approval boundary may wake one paid turn.
- token policy: deterministic extraction first; qualified Ollama only for a bounded mechanical operation; paid models for design and judgment. Savings remain UNMEASURED without a controlled pair.
- Ollama policy: calculator only, no design, verdict, or approval. Use only a current digest/task type marked QUALIFIED and independently compare output to source. Same-cause failure twice ends that route.
- verification: diff, fixed acceptance, unchanged test hashes, usage ledger, and remote SHA outrank worker reports. Empty output is failure.
- completion: U72 currently fails at 3.14x. Count only pairs with identical input hash, acceptance hash, task type, and model family; baseline and thrift must both PASS and have independent verification. Use the latest 10 valid pairs as the decision window; retain older rows as immutable history.
- tool roles: Codex plans and judges from packets; Claude implements one atomic subtask per card; Antigravity researches or independently reviews only when ACTIVE; Ollama handles qualified mechanical work after deterministic tools.
- approvals: local PLAN, cards, docs, tests, and dry-runs continue without interruption. Deletion, remote push, deploy/public posting, payment, and account, credential, permission, or system-setting changes require fresh action-specific approval.
- stop: hash mismatch, duplicate ownership, scope overlap, fixed-test mutation, outside write, budget overrun, P1, or approval boundary.

# Implementation requirements

1. Before editing, report `DUPLICATE_NO_CHANGE` if another owner or branch is implementing U76-A.
2. Add an optional comparison envelope to usage rows without breaking existing `uaos-usage-v2` rows. A valid pair requires the same non-empty `comparison_id`, `input_hash`, `acceptance_hash`, `task_type`, and model family; one row is `baseline_paid`, one is `thrift`; both outcomes are PASS and independently verified.
3. The report is deterministic and read-only. It returns `UNMEASURED` for 0-9 valid pairs and `MEASURED` only for the latest 10 valid pairs. Malformed, secret-bearing, unmatched, cross-model, failed, self-verified, or duplicate rows are excluded with counts.
4. Do not delete or rewrite ledger rows. Do not use an arbitrary half-life. Older valid pairs remain auditable but have zero decision weight outside the latest-10 window.
5. Report input, output, cache-read, cache-creation, wall time, quality outcome, and rework separately. Do not collapse them into one score and do not let one improved metric hide a regression.
6. Add red-first tests for unmatched rows, fewer than 10 pairs, exact 10-pair measurement, cross-model rejection, failed acceptance, self-verification, duplicates, immutable input, and one metric regression.
7. Use `worker: apply` with zero model tokens for the exact patch. Record wall time and acceptance. Do not call Claude recursively or invoke Ollama for this deterministic task.
8. Return FACT / EVIDENCE / VERDICT / NEXT in English under 1800 characters and include changed paths, exact commands, exits, test count, wall time, and session usage receipt.
