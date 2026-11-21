# U251-TIMING — bounded diagnostic execution, not release admission

Owner: antigravity native desk `1e097d46-f16a-4361-819e-862ef9869399`. Judge: codex.
Work ID: U251-TIMING. Maintained contract; generated traces are disposable evidence.

Goal: determine whether a reproduced failure of the unchanged frozen scheduler test counts overlapping owners or legitimate sequential owners. Prior controlled timing proves sequential double ACK is possible; it does not establish the original uninstrumented full-run cause.

Primary evidence: https://docs.python.org/3.14/library/multiprocessing.html#synchronization-between-processes . A start Event is distinct from a readiness Barrier; verify actual arrival/ownership timestamps.

Inputs (read-only, verify before execution):
- `.work/desk_261026_2/u251_judge/full_regression/stage_1/tests/test_u42_r1_hardening.py`: SHA256 `B50FB4D2D4AC91363632427EB4C6DDE9C44A3981158E5F756AE7AB01C8FE1410`.
- Same stage `v7_harness/rsi_release.py`: SHA256 `101141F2B409AE655596B1166DEB249BA55E19F53C5F3DCF4BC6885252A89FC2`.
- Full failure receipt `full_regression/final.json`: SHA256 `1A03C6BDFAFD9A66A574DAD5842157BCBCE2338FC37943C3B37F6716CA6C3F57`.
- Existing `full_regression/diagnosis_timing/summary.json`: SHA256 `7DD331BAB20E9C35DA51140CCF3EB2903FBB7B475C7F88DA0A82822AE1458080`.
The last two paths share prefix `.work/desk_261026_2/u251_judge/`.

Allowed output ONLY: `.work/desk_261026_2/u251_timing_proof/**`. No other writer owns this output scope. Verify master phase U251-TIMING still names this exact native owner and READY/ACTIVE before writing; otherwise stop.

Execution: provider-free native Python tools only. At most two executions of the original frozen test, total 120 seconds from actual execution start. Instrument process call/fetch/lock timing without editing production source, frozen evaluator, or changing test decisions. Use owned temporary fixtures only. No full-suite rerun, network, provider subcalls, OAuth capture, source promotion, commit/push/install, runtime/global-rule/settings/evaluator changes. Remote worker budget zero; monetary budget zero. Stop on hash mismatch, scope/ownership change, missing timestamps, repeated same-cause failure, or deadline. Record incomplete work as UNKNOWN.

Machine-checkable output: `result.json` containing work_id, exact input hashes before/after, child PIDs and exits, monotonic call/fetch/lock-or-bounded-call intervals, observed statuses, overlap classification, test exit, attempts, wall_seconds, paid_calls=0, source_test_edits=0, and limitations. Include raw trace and reproduction command. Call intervals do not prove exact lock boundaries; label that distinction.

Judgment gate: classify reproduced non-LOCKED owners by actual time overlap. No reproduction or missing trace is UNKNOWN, never PASS. Do not clear original full failure, declare the lock universally atomic, or authorize release. All release/Haiku holds remain.

One final evidence reply via `coord deliver`; set per-process `UAOS_AGY_AUTO=0` for internal delivery to avoid a redundant headless text-only answer. Published is not read/ACK or completed. No status-only automatic response is requested.
