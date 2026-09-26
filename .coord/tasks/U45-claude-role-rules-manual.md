```contract
work_id: U45_CLAUDE_ROLE_RULES
worker: claude
goal: Separate the installed UAOS common block from three minimal tool role adapters.
inputs:
- .coord/PROJECT_MANUAL.md sha256=bebe9ed7a40600f64a008eeb643f1d4d38736ee7727fcc55cd0d9fa921871674
- .coord/tasks/U45-claude-role-rules-instructions.md sha256=0315d1338ead771ffbd24378fc321468722e7b35bede58f707e16d5a9d024411
- uaos_everywhere/uaos_global_rule_block.md sha256=c1413aeaee9ee9cfb68d8abf48c65d8f6da0d540770ead049782b7328562ff42
- v7_harness/global_install.py sha256=25fb8a3f9b834037884f951f102dae8afeb10f38c550a58d9ee500e251ee0023
- tests/test_u37_install_everywhere.py sha256=d870b81afe23c20bb292d2ba2a499cb5656e3963ebabed3f7622cfabb3afd928
allow:
- uaos_everywhere/adapters/codex.md
- uaos_everywhere/adapters/claude.md
- uaos_everywhere/adapters/antigravity.md
- v7_harness/global_install.py
- tests/test_u37_install_everywhere.py
acceptance: python -m unittest tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 600
remote_budget_tokens: 180000
remote_budget_usd: 0.3
```

## Instructions for the worker

# U45 Claude worker process manual

Read and obey the full project manual below. This content is part of the call, not a path-only reference.

## Full project manual

- work_id: U45
- Goal: make UAOS 0.3.0 portable to unrelated software projects by separating one minimal common invariant block from three short role adapters.
- Ownership: Codex is coordinator and independent judge; Claude is author only.
- State machine: Codex ACTIVE leads; Claude acts only when Codex is LIMITED/ABSENT and Claude is ACTIVE; Antigravity acts only when both are LIMITED/ABSENT and Antigravity is ACTIVE; UNKNOWN fails closed.
- Budget: do not convert remaining percentages or reset windows into tokens. Enforce token, USD, and wall-time caps independently.
- Delegation: the entire linted contract and process manual must be sent in the actual call.
- Safety: no deletion, push, deploy, credential/permission changes, network, or edits outside allow.
- Verification: tests and installer drift decide; Claude must not claim acceptance.

## Mechanical implementation assignment

1. Create three adapter files under `uaos_everywhere/adapters/`: `codex.md`, `claude.md`, `antigravity.md`.
2. Each adapter must be at most 6 nonblank bullet lines and contain only role-specific behavior. Do not repeat the common safety, contract, retention, or RSI rules.
3. Update `v7_harness/global_install.py` so each tool receives the byte-identical common block followed by only its adapter inside the existing UAOS markers. Preserve preview/apply/check/uninstall behavior and unrelated user text.
4. Update `tests/test_u37_install_everywhere.py` with deterministic assertions that all three results contain the same common block and only the matching adapter. Do not weaken existing tests or branch on test names/runners/fixtures.
5. Do not edit version, READMEs, U45 tests, PLAN, docs, or usage ledger.

Acceptance is run by the harness. Stop on two failures with the same cause, budget exhaustion, or scope escape.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
