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
