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
