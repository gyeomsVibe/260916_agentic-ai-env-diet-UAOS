```contract
work_id: U279-F1
worker: local
goal: Reorder checks in deliver._wants_wake per the U279-F1 contract so an ACTIONABLE answer or explicit verdict wakes despite verdict_requested=False while NOTICE/ACK_ONLY still never wake
inputs:
- v7_harness/coord/deliver.py sha256=23e43ae54243f2c5e1b7147688dabe682bf526d0302924d50d42f50912def565
- tests/test_u279_answer_wakes.py sha256=fa1a4f81129dfe87ee812a64b1793bf43e4fd16b5c1554dd24bd743b5198a93b
- tests/test_u194_verdict_wakes_agy.py sha256=427325fa314aa85808186dacbf96866714a16d61b08bd2a0ed03560673aeef8c
- tests/test_u141a_wake_policy.py sha256=c86e5e58dd07c588821bddfa83b6c1f55331399ce1ca1a54718c320c97bfd72d
- tests/test_u141b_producer_wake.py sha256=d63dfa8161bf4352e782ddf12f112c87169dcad93aa009d4e5b36ad6cadee3a4
- tests/test_u15_notify_codex.py sha256=4cb126184911afa434acc5c412994952a9266f91def3f2c9a891be52095b8081
allow:
- v7_harness/coord/deliver.py
context_allow:
- v7_harness/coord/deliver.py
- tests/test_u279_answer_wakes.py
acceptance: python -m pytest -q -p no:cacheprovider tests/test_u279_answer_wakes.py tests/test_u194_verdict_wakes_agy.py tests/test_u141a_wake_policy.py tests/test_u141b_producer_wake.py tests/test_u15_notify_codex.py && python -m pytest -q -p no:cacheprovider
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# U279-F1 source-only contract: an ACTIONABLE answer wakes even when it requests no verdict

Author: Claude 0d09a2d7 (AGY LIMITED, user order 2026-10-28 to split Codex's load). Judge: Codex.
Why: Codex U279 design verdict P1-1. On main, `deliver._wants_wake` returns False whenever `verdict_requested is False`,
before it looks at `wake_class="ACTIONABLE"` or an explicit `verdict`, so a PASS/REVISE answer can be lost (U277 class).

## Allowed change

Only `v7_harness/coord/deliver.py`, only `_wants_wake`. Order of checks becomes:
1. `wake_class in ("NOTICE", "ACK_ONLY")` or the ACK_ONLY marker → False (unchanged, always wins).
2. `wake_class == "ACTIONABLE"` or `bool(verdict)` or `verdict_requested is True` → True.
3. `verdict_requested is False` → False (a plain letter marked "no verdict asked" stays quiet).
4. otherwise `_requires_wake(message)` (unchanged).

No pool, batching, session rotation or cap change (those wait for Codex's separate replan).

## Acceptance

- `python -m pytest -q -p no:cacheprovider tests/test_u279_answer_wakes.py` (red now: 3 failed).
- Unchanged regressions: `tests/test_u194_verdict_wakes_agy.py tests/test_u141a_wake_policy.py tests/test_u141b_producer_wake.py tests/test_u15_notify_codex.py`.
- Full suite exit 0.

## Invariants (Codex relay_a0991be3)

- NOTICE / ACK_ONLY (class or marker) always wins: zero dispatch, whatever `verdict` or `verdict_requested` say.
- ACTIONABLE class or explicit verdict with `verdict_requested=False` keeps its wake (one dispatch).
- `_wants_wake` decides only wake or not; message_id, digest, target, requester, request/session binding and the
  receiver ACK path (mailbox claim, `coord ack`) are untouched. No session rotation, pooling, UUID replacement, caps.
- Evaluators frozen: tests/test_u279_answer_wakes.py and the four named regressions are not edited by the worker.

## Limits and stop

- Output: one function body, at most ~10 changed lines in `v7_harness/coord/deliver.py`; anything else is rejected.
- Time cap 900 s per attempt; worker local (Ollama, 0 paid tokens); no paid fallback without a new contract.
- Stop: any need to change another function or file, or a second local failure of the same cause → report to Codex.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
