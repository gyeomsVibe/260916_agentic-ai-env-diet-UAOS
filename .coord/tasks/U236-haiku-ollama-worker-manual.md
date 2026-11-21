```contract
work_id: U236A-L1
worker: local
goal: claude_worker rejects an envelope whose modelUsage keys differ from the pinned full model id
inputs:
- v7_harness/delegation.py sha256=9f5c57c144d5a1069b5d77e09d025a355f56fd37637c78c6da7a2b27c2d8e224
allow:
- v7_harness/adapters/claude_worker.py
- v7_harness/manual.py
context_allow:
- v7_harness/adapters/claude_worker.py
- v7_harness/manual.py
- tests/test_u236a_model_pin.py
- tests/test_u38_cost_gate_and_claude_worker.py
acceptance: python -m unittest tests.test_u236a_model_pin tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_u44_claude_contract tests.test_u45_general_uaos tests.test_u46_followup_fixes tests.test_u69_admission_gate tests.test_u70_local_qualification tests.test_u98d_delegate_first tests.test_u106_local_first tests.test_u106_subcontract tests.test_u34_precision_harness tests.test_u36_evidence_gated_rsi
forbidden: editing or deleting tests; new workers or adapters; routing or cascade changes; hub or language policy; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

# U236a: Pinned-Model Guard for Existing Claude Worker (Bounded Slice)

## 1. Scope & Alignment with Codex Review (`.coord/results/U236-CODEX-SCOPE-REVIEW.md`)
- **Bounded Slice (`U236a`)**: Reuses existing `v7_harness/adapters/claude_worker.py` (`worker: claude`) and `v7_harness/manual.py`. Adds deterministic fail-closed verification that a pilot run specifying a pinned full model ID (e.g., `claude-haiku-5-5`) rejects any CLI result whose `modelUsage` keys do not match `{pinned}` (`MODEL_MISMATCH`), records `resolved_models` in the envelope, and rejects alias model names (`haiku`, `sonnet`, `opus`) in `v7_harness/manual.py` when `worker == "claude"` and `model:` is specified.
- **Deferred Non-Goals**: Global Argon routing policy, `local -> haiku` cascade changes, agent-to-agent language migration, `.claude/agents/uaos-haiku.md` subagent wiring, and any savings claims stay deferred to separate cards (`U237`–`U240`).
- **Companion Worktree Contract**: Aligned with Claude's `.claude/worktrees/user-conversation-setup-6aa5f9/.coord/tasks/U236-worker-slice-revised-contract.md` (`sha256=ae804aac367599c52f2d0572fcad35a7cdc58b98f50bb18b831240649e553a2d`, frozen base `origin/main` `72c98849e68dc55bced325f4de8ba1162fe55633`, `claude_worker.py` `sha256=e2fe98b551e26421ab3f8f08dfbeb293cc77d6d2d6fc93638bb90dc0b415079f`).

## 2. Instructions for the Worker
- In `v7_harness/adapters/claude_worker.py`:
  1. Add `def model_mismatch(result: dict, pinned: str) -> str:` that reads `keys = sorted(str(k) for k in (result.get("modelUsage") or {}).keys())`, returns `""` when `keys == [pinned]`, and otherwise returns `f"MODEL_MISMATCH: expected {pinned}, got {keys}"`.
  2. In `main`, after `result` is parsed as a `dict` and `usage = usage_from(result)` is computed, set `usage["resolved_models"] = sorted(str(k) for k in (result.get("modelUsage") or {}).keys())` (or include `resolved_models` in the envelope), and if `args.model` was explicitly passed and `model_mismatch(result, model)` is non-empty, return `envelope("ERROR", "", usage, mismatch)` (exit 1, fail closed, no files written).
- In `v7_harness/manual.py`:
  1. In `lint()`, when `worker == "claude"` and `contract.get("model")` is in `("haiku", "sonnet", "opus")`, append `"MODEL_ALIAS: worker claude needs a full model id"`.

## 3. Fixed Judge-Owned Negative Acceptance (`tests/test_u236a_model_pin.py`)
1. Envelope `modelUsage` = `{"claude-haiku-5-5": {...}}` -> `SUCCESS` (exit 0), `resolved_models` recorded.
2. Envelope `modelUsage` = `{"claude-sonnet-4-6": {...}}` -> `MODEL_MISMATCH` (exit 1), fail closed.
3. Envelope without `modelUsage` or empty `{}` -> `MODEL_MISMATCH` (exit 1), fail closed.
4. Contract `worker: claude` with `model: haiku` (alias) -> `lint()` returns `ok=False` with `MODEL_ALIAS`.
5. Contract `worker: claude` without `remote_budget_usd` -> `lint()` returns `REMOTE_WITHOUT_USD_CAP`.
6. Contract `worker: claude` with `judge: claude` -> `lint()` returns `SELF_JUDGE`.
7. Existing `test_u38_cost_gate_and_claude_worker` and `test_u68_claude_worker_utf8` pass unchanged.

## 4. Primary References
- Anthropic Claude Code Model Configuration: https://code.claude.com/docs/en/model-config
- Anthropic Claude Code CLI Reference: https://code.claude.com/docs/en/cli-reference

## Output
- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
