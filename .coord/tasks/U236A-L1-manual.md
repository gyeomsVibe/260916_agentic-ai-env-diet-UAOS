# U236a: opt-in exact-model guard for the existing Claude worker (revised contract, rev 2)

Author: claude (contract only; no source written). The Antigravity manual
`.coord/tasks/U236-haiku-ollama-worker-manual.md` stays untouched. Rev 2 answers Codex REVISE_EXECUTION
(relay_a6e033c2) on rev 1 (sha256 ae804aac...); Antigravity note (.coord/results/U236A-AGY-CONTRACT-AUDIT.md,
top-level `resolved_models`) is folded in.

## Goal and non-goals

- Goal (one slice): a contract that opts in with `model_pin: exact` and names a full model id runs on exactly
  that model or fails closed. Without the opt-in, behavior is byte-for-byte the legacy behavior.
- Non-goals (later cards, each with its own contract): Argon hub routing, `local -> haiku` preference, agent
  language rule, `.claude/agents/uaos-haiku.md`, global settings, any cost-cap or savings claim, any paid call.
  U235 provenance HOLD and U229 release gates stay as they are.

## Frozen base and evidence

- Base: `origin/main` 72c98849e68dc55bced325f4de8ba1162fe55633, runtime 0.3.0-1df66c523ee7.
- Read in the base:
  - `v7_harness/adapters/claude_worker.py` builds `claude -p ... --model <model>` (lines 89-91) and passes
    `--max-budget-usd`. Its own docstring (line 15) and `cap_overshoot` (lines 130-137) record that the CLI
    checks that dollar threshold after a turn and can overshoot (U45-G7: $0.319 on a $0.30 cap). It is a
    threshold with recorded overshoot, not a hard pre-spend cap. Rev 1 said otherwise; that claim is withdrawn.
  - `DEFAULT_MODEL` is the alias `sonnet` (line 39); legacy contracts and fixtures rely on aliases and on
    envelopes without `modelUsage`. Both stay valid outside the opt-in.
  - `v7_harness/cli.py:361-366` (`_with_cap`) appends worker flags from the contract; `cli.py:387` passes the
    contract `model:` to the worker.
- Official interface: https://code.claude.com/docs/en/model-config (aliases vs full ids, provider-dependent
  alias resolution); https://code.claude.com/docs/en/cli-reference (`--model`, `--output-format json`).
- Model evidence: UNKNOWN. A search of `.coord/runs/` found no recorded envelope with `modelUsage`. This card
  makes no paid probe. Real use of `model_pin: exact` stays BLOCKED until a separate bounded evidence card
  (U236E, own contract, own cap, non-author judge) records a sanitized real envelope; until then the guard is
  proven only against fake-CLI fixtures and fails closed on real runs that lack `modelUsage`.

## Alternatives (decision: A)

- A. Opt-in flag on the existing adapter: `--require-model <id>`; `cli.py` passes it only when the contract
  says `model_pin: exact`. About 25 lines over three functions; legacy path untouched.
- B. New `haiku_worker.py` plus `worker: haiku`. Duplicates isolation and usage code; rejected.
- C. Subagent file only. No pilot route, no enforcement; rejected.

## Enforcement plan

- Opt-in only: `claude_worker.main` checks the model only when `--require-model` is given. Then every key of
  the envelope `modelUsage` must equal it; any other key, or no `modelUsage`, returns status `FAILED` with error
  `MODEL_MISMATCH: expected <id>, got <sorted keys>`. No fallback, no retry, no worker switch.
- Receipt: with `--require-model`, the envelope gets a top-level `resolved_models` list (sorted keys), never
  inside `usage`, so `usage` values stay integers.
- Lint: only when `model_pin: exact` and `worker: claude`, a `model` of `haiku`, `sonnet` or `opus` (or a
  missing `model`) is the error `MODEL_ALIAS: model_pin exact needs a full model id`. No other lint change.
- Cap and timeout: unchanged; the dollar threshold may overshoot and is recorded by `cap_overshoot`.

## Fixed acceptance (judge-owned, frozen before implementation)

The judge (codex) writes `tests/test_u236a_model_pin.py` with a fake CLI (no paid call, no network) before the
worker runs; at dispatch its sha256 joins `inputs` (lint refuses a missing input, so until then it is listed in
`context_allow` only). Existing tests are not altered. It must cover:

1. Opt-in, `modelUsage` = {claude-haiku-5-5}, `--require-model claude-haiku-5-5` -> SUCCEEDED, top-level
   `resolved_models` = ["claude-haiku-5-5"], `usage` values all int.
2. Opt-in, `modelUsage` = {claude-sonnet-5-5} -> FAILED, MODEL_MISMATCH, no files written back.
3. Opt-in, envelope without `modelUsage` -> FAILED, MODEL_MISMATCH.
4. Opt-in, `modelUsage` with two keys, one matching -> FAILED, MODEL_MISMATCH.
5. No opt-in, envelope without `modelUsage`, model alias `sonnet` -> legacy SUCCEEDED, no `resolved_models`.
6. Lint: `model_pin: exact` with `model: haiku` -> MODEL_ALIAS; same contract without `model_pin` -> no
   MODEL_ALIAS; `model_pin: exact` with no `remote_budget_usd` -> REMOTE_WITHOUT_USD_CAP still fires.
7. `cli.py` passes `--require-model` only for `worker: claude` with `model_pin: exact`.
8. Legacy suites in `acceptance` pass unchanged.

## Ownership, rollback, stop

- One writer: the Ollama worker (local) in an isolated worktree on branch `claude/u236a-model-pin` from
  72c98849; after two same-cause Ollama failures, `worker: apply` with `apply_after`. Claude does not edit
  source directly; Claude opens the PR, Antigravity audits, codex judges, Antigravity merges (match-head).
- Rollback: revert the single commit; runtime rollback to 0.3.0-1df66c523ee7.
- Stop: two failures with the same cause; input hash mismatch; edits outside `allow`; judge test file absent
  at dispatch; 900 seconds per worker step.

```contract
work_id: U236A-L1
worker: local
goal: claude_worker --require-model fails closed when modelUsage keys differ from the pinned full model id
inputs:
- v7_harness/adapters/claude_worker.py sha256=e2fe98b551e26421ab3f8f08dfbeb293cc77d6d2d6fc93638bb90dc0b415079f
- tests/test_u236a_model_pin.py sha256=54441760f3e03595d249e5b257fb190e209e0937742cc52ecbfc053684321dd6
allow:
- v7_harness/adapters/claude_worker.py
- v7_harness/manual.py
- v7_harness/cli.py
context_allow:
- tests/test_u236a_model_pin.py
- tests/test_u38_cost_gate_and_claude_worker.py tests.test_b20_model_flag tests.test_cli tests.test_m2_pilot tests.test_b41_bundle
acceptance: python -m unittest tests.test_u236a_model_pin tests.test_u38_cost_gate_and_claude_worker tests.test_u68_claude_worker_utf8 tests.test_u44_claude_contract tests.test_u45_general_uaos tests.test_u106_local_first tests.test_u106_subcontract tests.test_u34_precision_harness tests.test_u36_evidence_gated_rsi tests.test_u46_followup_fixes tests.test_u69_admission_gate tests.test_u70_local_qualification tests.test_u98d_delegate_first
forbidden: editing or deleting tests; changing behavior without --require-model or model_pin exact; new workers or adapters; routing or cascade changes; hub or language policy; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; judge test absent; no output; 900 seconds
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

1. `v7_harness/adapters/claude_worker.py`: add `model_mismatch(result: dict, pinned: str) -> str` returning ""
   when `set(result.get("modelUsage") or {}) == {pinned}`, else
   `f"MODEL_MISMATCH: expected {pinned}, got {sorted(result.get('modelUsage') or {})}"`. In `main`, add
   `parser.add_argument("--require-model", default=None)`. Only when it is set: after the CLI result is parsed
   and before any success envelope, call `model_mismatch`; if non-empty return
   `envelope("FAILED", "", usage, error)`; otherwise add top-level `resolved_models` (sorted keys) to the
   envelope dict. When it is not set, change nothing.
2. `v7_harness/cli.py`, inside `_with_cap` only: when `worker == "claude"` and
   `str(contract.get("model_pin") or "") == "exact"`, also append `"--require-model", <contract model>`.
3. `v7_harness/manual.py`, in the `worker == "claude"` block: when `contract.get("model_pin") == "exact"` and
   the contract `model` is missing or in (`haiku`, `sonnet`, `opus`), append
   `"MODEL_ALIAS: model_pin exact needs a full model id"`.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
