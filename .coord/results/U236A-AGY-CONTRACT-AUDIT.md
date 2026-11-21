# U236a Antigravity Contract Audit

- **Target Contract**: `.claude/worktrees/user-conversation-setup-6aa5f9/.coord/tasks/U236-worker-slice-revised-contract.md` (`sha256=ae804aac367599c52f2d0572fcad35a7cdc58b98f50bb18b831240649e553a2d`) and synced root contract `.coord/tasks/U236-haiku-ollama-worker-manual.md`.
- **Auditor**: Antigravity (independent contract & counterexample reviewer; Judge is Codex).
- **Verdict**: `PASS_CONTRACT_WITH_1_NOTE` (ready for Codex contract approval & judge-owned test pinning).

## 1. Deterministic Lint Evidence
- Command: `python C:/Users/Kimyoongyeom/.uaos/uaos.py pilot manual lint --manual .claude/worktrees/user-conversation-setup-6aa5f9/.coord/tasks/U236-worker-slice-revised-contract.md --source .claude/worktrees/user-conversation-setup-6aa5f9`
  - Exit code: `0` (`ok: true`, `errors: []`).
  - Warning noted: `RELATED_TESTS_NOT_IN_ACCEPTANCE:tests.test_u46_followup_fixes tests.test_u69_admission_gate tests.test_u70_local_qualification tests.test_u98d_delegate_first`.
- Synced root `.coord/tasks/U236-haiku-ollama-worker-manual.md` includes those 4 related test modules in `acceptance:` so it lints with `ok: true, errors: [], warnings: []`.

## 2. Counterexample Check Against Codex Scope Review (`.coord/results/U236-CODEX-SCOPE-REVIEW.md`)
1. **Contract Gate**: Fenced ```` ```contract ```` block present with explicit `worker: local`, `judge: codex`, pinned input sha256, `timeout_s: 900`, `remote_budget_tokens: 0`, and deterministic `stop` conditions.
2. **Scope Split**: Properly narrowed to `U236a` (reusing `v7_harness/adapters/claude_worker.py` + `v7_harness/manual.py` for full-model-ID pinning and `modelUsage` verification). Argon hub policy, language rules, and subagent files are deferred.
3. **Counterexample / Implementation Note for Pinned Test (`tests/test_u236a_model_pin.py`)**:
   - In `v7_harness/pilot.py`, the pilot checks the worker JSON envelope `status == "SUCCESS"` (and non-zero return code). Whether `claude_worker.py` returns `envelope("ERROR", "", usage, error)` or `envelope("FAILED", "", usage, error)` where `error` starts with `"MODEL_MISMATCH:"`, `envelope()` returns exit code `1` whenever `status != "SUCCESS"`. The judge-owned `tests/test_u236a_model_pin.py` should assert `rc == 1`, `env["status"] in ("ERROR", "FAILED")`, and `"MODEL_MISMATCH" in env["error"]`.
   - In `v7_harness/usage_accounting.py` / `pilot.py`, `usage` values in `USAGE_KEYS` are `int`; if `resolved_models` (a `list[str]`) is returned, placing it as top-level envelope key `"resolved_models"` (alongside `"usage"`) avoids breaking any `isinstance(v, int)` assumptions on `usage` dicts.

## 3. Primary Sources
- https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/cli-reference
