```contract
work_id: U55
worker: apply
goal: Measure run-to-run input-token spread from the usage ledger and propose (never adopt) a token ratchet ratio within rsi's 1.0..3.0 bounds; UNCALIBRATED below 3 qualifying groups (docs/49 U-TOK-3 calibration).
inputs:
- v7_harness/rsi.py sha256=74b212f234a70b315c23a6e8fa8a6e0e1c8b9f0c494b2383c6dc989622588a8b
allow:
- v7_harness/token_calibration.py
- v7_harness/cli.py
- tests/test_u55_token_calibration.py
- tests/fixtures/u55_ledger.jsonl
acceptance: C:/Python314/python.exe -m unittest tests.test_u55_token_calibration tests.test_cli tests.test_u36_evidence_gated_rsi tests.test_b20_model_flag tests.test_b23_concurrency_summary tests.test_b25_db_unavailable tests.test_b41_bundle tests.test_r2_minimal_control tests.test_u15_coord_cli tests.test_u15_pilot_autolog tests.test_u15_stream_append tests.test_u16_local_worker tests.test_u17_lane_worker tests.test_u23_mailbox tests.test_u32_sentinel_bell tests.test_u33_pilot_autolog_default tests.test_u34_precision_harness tests.test_u37_install_everywhere tests.test_u38_cost_gate_and_claude_worker tests.test_u45_general_uaos tests.test_u46_agy_review tests.test_u46_followup_fixes tests.test_u46_pilot_judge tests.test_u47_d1_local_usage tests.test_u47_j5_judge_budget tests.test_u47_r2_retention_alert tests.test_u48_default_workdir tests.test_u57_desk_signals
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Instructions for the worker

Status: DRAFT contract (BACKLOG, docs/49 §5.0). It is not runnable yet. The author adds the ===FILE blocks when the card is
picked up, then rebuilds and re-lints this manual. Judge codex. The author never approves its own bundle.

Card: U55, docs/49 U-TOK-3 (token ratchet), calibration step only.

Problem: docs/49 proposed failing a run whose tokens exceed 1.2x the verified minimum, and called 1.2 an initial value to re-tune after 3 measurements. Today `rsi.gate` has `max_cost_ratio` 3.0 (bounds 1.0..3.0), which compares medians. No measured run-to-run spread exists, so 1.2 has no evidence behind it and must not become a gate yet.

What:
- New stdlib-only module v7_harness/token_calibration.py.
- It reads the existing usage ledger rows (.coord/usage/runs.jsonl format; tests use a fixture copy, never the live file).
- It groups rows by (task kind, worker, model) and reports, for each group with n >= 3 real runs:
  - median input tokens;
  - the max/min ratio;
  - the ratio of the 90th percentile to the median.
- Rows with input_tokens == output_tokens == 1 are placeholders; exclude them the same way rsi.py already does.
- It proposes a ratchet ratio = the largest p90/median across qualifying groups, rounded up to 0.05, clamped to the existing 1.0..3.0 bounds. It returns UNCALIBRATED when fewer than 3 groups qualify.
- CLI: `pilot calibrate-tokens --ledger <file> [--json]` prints the proposal. It never writes a policy file and never changes `max_cost_ratio`. Adopting a value is a separate card that a judge approves.

Tests (tests/test_u55_token_calibration.py):
1. A fixture ledger with three groups of known spread gives the hand-computed ratio.
2. Placeholder rows and groups with n < 3 are excluded; with fewer than 3 qualifying groups the result is UNCALIBRATED.
3. The live `rsi.DEFAULT_POLICY` stays byte-identical after a run. The test compares the repr before and after.
4. Identical input gives identical JSON output.

Red first: on HEAD, test 1 fails with an import error.

Out of scope: changing `max_cost_ratio`, adding a token axis to `rsi gate`, and any paid or local model call.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
