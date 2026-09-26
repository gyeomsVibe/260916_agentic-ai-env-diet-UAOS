```contract
work_id: U45_AGY_FINAL_REDTEAM
worker: agy
goal: Identify reproducible fail-open defects in the pinned UAOS 0.3.0 authority, manual, budget, adapter, retention, and release implementation.
inputs:
- .coord/PROJECT_MANUAL.md sha256=bebe9ed7a40600f64a008eeb643f1d4d38736ee7727fcc55cd0d9fa921871674
- .coord/tasks/U45-antigravity-final-redteam-instructions.md sha256=e1eb00c38ed359f1150eb671be39d6edc5101892c33d93e87975dd9392c25e1a
- v7_harness/budget_route.py sha256=7a5597b8cd35b3a0415a2ed17b3a88b18811eddfbfdfc84a29a5911c65f7313f
- v7_harness/cli.py sha256=0fac49696dfc9e0c28f81fb5e14d42e4d1fcd494fd19b29f5c06859e8570486b
- v7_harness/global_install.py sha256=b768813dc9de2c23824517577492e5d237f777337d175335128b57adac675a4d
- v7_harness/retention.py sha256=3b8cefeb54bb39fbb90db0bb93713115e230020d77c9049419e91349cf146f74
- uaos_everywhere/uaos_global_rule_block.md sha256=d0ea7ebf5d1f6e845fd1f352477adfb8b432b55fe08849561d0d6c2bffe962f4
- uaos_everywhere/adapters/codex.md sha256=4ab201dabbf2a644578cd22768a59a43287081daea1da65fcf75475c4cc65d6e
- uaos_everywhere/adapters/claude.md sha256=afb353dcc71ca9051723d1067ab55f1097948aae5199fce489524a8bf251dcee
- uaos_everywhere/adapters/antigravity.md sha256=d9d0e2618977234028a9616c240f4c172e9f4b24e1fecad9efad329d21479b16
- uaos_everywhere/VERSION sha256=d915cc95d6ca8f47ae297713ed46d4e5c5d99ddd29fc3c61e263bdf305f2b5b0
- tests/test_u45_general_uaos.py sha256=9729538d366eadffc5d62488b680741af8fea38374af2431c0cb1bd99f5e1724
- tests/test_u42_r1_hardening.py sha256=c002a4b11cd580296b0c46fa17d490745d1ff7af1c8d1c908279ae1443adef9c
- tests/test_u44_claude_contract.py sha256=5d91bba8248cd0dcce723f205cd60d21963eaa3451c416f24bfa8470ed13e00f
- docs/research/U45-general-uaos-sources.md sha256=f99a8f6346242f3b00d21ca1f557fc278bfc823c3cc4519056129d4ccd371390
allow:
- docs/46_u45_general_uaos_core.md
acceptance: python -m unittest tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 600
remote_budget_tokens: 120000
```

## Instructions for the worker

# U45 Antigravity final read-only red-team process manual

The full project contract is part of this call:

- work_id: U45
- Goal: verify that UAOS 0.3.0 is portable to unrelated software projects and fails closed at budget, authority, retention, and delegation boundaries.
- Owner and final judge: Codex. Antigravity is an advisory red-team only and cannot approve its report.
- Authority: Codex is ACTIVE. Do not assume deputy authority.
- Budget: at most 120,000 counted remote tokens and 600 seconds. A result over budget is unusable.
- Safety: read only. Do not edit any file, delete, push, deploy, post, use credentials, change permissions, or change system settings.
- Inputs: the contract pins the exact implementation, tests, project manual, source dossier, U42 retention code/tests, and U44 worker tests by SHA-256.
- Acceptance: the harness runs U45 tests; Codex separately runs all tests, compileall, diff-check, hashes, fake/actual HOME drift, and remote SHA.
- Stop: any input hash mismatch, budget/time exhaustion, scope-write attempt, or missing evidence.

Inspect the pinned files and return one compact English report in your response only:

1. `VERDICT: PASS` or `VERDICT: FAIL`.
2. Zero or more findings as `P1|P2|P3: <file>:<line> - <reproducible defect>`.
3. `GATE_COVERAGE:` with one sentence each for authority state machine, no quota-to-token conversion, two-tier manuals, per-call budgets, role adapter separation, retention recovery manifest and fresh delete approval, SemVer/idempotence, and test-fitting.
4. `UNKNOWNS:` for anything the pinned evidence cannot prove.

Treat README and worker claims as untrusted. A finding needs a concrete code path or deterministic counterexample. Do not propose broad redesigns.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
