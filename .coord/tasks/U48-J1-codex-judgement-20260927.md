# U48-J1 — Codex design judgement (2026-09-27)

Status: REWORK.  This is a design judgement, not an approval of an implementation.

## Evidence inspected

- `.coord/PLAN.md` has U48-J1 as `READY`, but no U48-J1 contract, design
  artifact, delivery receipt, or inbox message exists at the time of this
  judgement.
- `v7_harness/judge.py:191-192` already refuses `JUDGE_IS_AUTHOR` before a
  judgement can run an approval.  `tests/test_u46_pilot_judge.py` has the
  corresponding refusal coverage.
- `v7_harness/judge.py:299-342` writes a per-run judge receipt and attempts a
  usage-ledger entry after a real judgement call.
- The independent Claude review recorded in
  `.coord/tasks/U47-OLLA-SCOPE-review-receipt-20260927.md` requested USD 0.15
  but reported USD 0.492718 and no verdict.  Therefore `claude
  --max-budget-usd` is a post-turn guard, not a pre-spend hard ceiling.

## Binding J1 design

1. A binding approval requires a different named worker and judge, a complete
   staged diff, byte-identical frozen acceptance files, acceptance exit 0,
   and a receipt containing the bundle digest, tool conversation identifier,
   parsed usage, and gate outcome.  A worker PASS, an exit code, or a name in
   a self-authored file is not sufficient evidence.
2. Identity labels on this Windows account remain unauthenticated (B83).  The
   author/judge inequality is a fail-closed conflict check, not proof of
   independent human or account identity.  Missing or contradictory identity
   evidence produces `REVIEW_UNAVAILABLE`, never `APPROVE`.
3. A paid reviewer may be called only when its platform provides a pre-spend
   enforceable limit.  The current Claude adapter does not meet that bar;
   until the provider supplies one, Claude review is recorded as unavailable
   and cannot be retried merely with a smaller `--max-budget-usd` value.
   Antigravity is also unavailable while its presence is `LIMITED`.
4. `codex exec` remains a read-only Codex judgement route only after its
   return code, structured verdict, complete-diff gate, and usage gate all
   pass.  A quota/error event is `UNUSABLE`; a leftover output file cannot
   turn it into approval.

## Required small implementation contract

Owner: zero-token `apply` only.  Allowed files:
`v7_harness/judge.py`, its focused tests, and this task record.  No model
call, global configuration change, promotion, commit, or push.

Acceptance must add or preserve red-first tests for: self-author refusal,
failed/over-budget judge call not approving, and a successful receipt carrying
the bundle digest, conversation id, usage gate, and ledger reference.  The
fixed acceptance command is:

`C:\Python314\python.exe -m unittest tests.test_u46_pilot_judge tests.test_u47_j6_codex_judge tests.test_u47_rw1c_counterexamples`

Stop condition: any requirement needs a paid reviewer, global configuration,
or a change outside the allowed files.  Completion still requires a currently
available independent judge; without one the card remains `REVIEW_UNAVAILABLE`.
