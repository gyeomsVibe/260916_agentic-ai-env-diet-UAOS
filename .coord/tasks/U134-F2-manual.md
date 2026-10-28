```contract
work_id: U134-F2
worker: agy
goal: per-letter OS-locked queue claim with scoped crash recovery in deliver.dispatch_queued (Codex relay_4e5ed6c2)
inputs:
- v7_harness/coord/deliver.py sha256=6cceeb12322f1718b20afed256685518433e71cbbfc53303e806d1784ed7b5e0
- tests/test_u134_f2_queue_claim.py sha256=891b0b502a02193270e143a61f7774a56fb5dbc2b88cc7ae545e63b0a14286e6
- tests/test_u134_dispatch_on_active.py sha256=f0f27169af71185282a66d447b8633b77c1d5878ffa2007f19e326b085ec697d
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u134_f2_queue_claim tests.test_u134_dispatch_on_active tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples tests.test_u134_f1b_cwd tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread tests.test_u120_agy_auto_reply tests.test_u127_agy_card_window tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_u49_dispatch_count tests.test_u49_guard_release_race tests.test_u49_mailbox_locked_ack
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 1800
remote_budget_tokens: 400000
paid_after: U134-L6
```

## Instructions for the worker

## Work Order U134-F2: per-letter queue claim with crash recovery (acting conductor Claude, Codex LIMITED)

Receipt: Codex rev3 verdict relay_4e5ed6c2 (2026-10-03) requires F2 as "a minimal one-letter-at-a-time claim with a
per-letter OS lifetime lock held across the ownership check, the send and the settle". Recovery must acquire that
lock, so a live paused owner is not stolen by age.

Red proof: on main deliver.py 6cceeb12, the fixed acceptance `tests/test_u134_f2_queue_claim.py` fails 2 of 5.
- A dead owner's `<id>.<hex>.taking` is never recovered.
- A corrupt marker overwrites the existing `<id>.failed` evidence.

### Change only `dispatch_queued` and `queued_letters` in v7_harness/coord/deliver.py, plus small private helpers
1. **Per-letter lock.** For each queued letter id, open `<queue dir>/<message_id>.lock` and take a non-blocking OS
   lock with the existing `_try_lock` and `_unlock` helpers (already imported from stream.py).
   - If the lock is busy, skip that letter: a live owner has it, even if that owner is paused.
   - Hold the lock from before the rename until after the settle. Never hold any global queue lock across the send.
   - Never unlink the `.lock` file. The OS releases the lock when its holder exits or dies.
2. **Letter ids.** Take them from both `<id>.json` markers and orphan `<id>.<hex>.taking` files in the queue folder.
   Build `queued_letters` (or a helper) so each id is processed once, in name order.
3. **Orphan recovery.** Holding the lock while an orphan `.taking` exists proves its owner is dead. Adopt that file as
   this dispatcher's taking file and keep the original message id.
   - If the mailbox claim of THIS message id is in `claimed/<message_id>_*.json` and the inbox file is absent, move it
     back to `inbox/<message_id>.json`.
   - Then write an attempt receipt with state `QUEUE_CLAIM_RECOVERED` under `delivery/attempts/`.
   - Do not call `box.recover_stale_claims` or touch claims of any other message id.
   - Leave the per-message dispatch guard to its existing U83 age rule (`_acquire_guard`, `GUARD_STALE_S`).
4. **Settle.** The settled reasons are unchanged. An `IN_FLIGHT` result means another dispatch guard is still young.
   It returns the letter to `<message_id>.json` without adding an attempt. Any other unsettled result adds one attempt
   and parks the letter after 3 tries, as today.
5. **Corrupt marker.** Park it as `<message_id>.failed` only if that name is free. Otherwise use
   `<message_id>.<hex>.failed`. Existing `.failed` bytes are never overwritten.
6. Add a comment for each new number and for each decision, next to it.
7. **Documented risk.** A crash after the remote send but before the accepted receipt can duplicate one send. State
   this in the `dispatch_queued` docstring.

### Fixed acceptance (frozen; do not edit any test)
`python -m unittest tests.test_u134_f2_queue_claim tests.test_u134_dispatch_on_active tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples tests.test_u134_f1b_cwd tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_u49_dispatch_count tests.test_u49_guard_release_race tests.test_u49_mailbox_locked_ack (plus the U115-U127 relay modules in the contract)`

### Forbidden and stop
- **Forbidden:** editing tests or any other file; deletion; promotion, commit or push; U144 work; changing the timeout
  or the guard age rule.
- **Stop:** two failures with the same cause, an input hash mismatch, or no output.
- **Return:** one DRY_RUN_PASSED bundle id for the independent judge.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
