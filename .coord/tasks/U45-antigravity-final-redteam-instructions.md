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
