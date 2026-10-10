```contract
work_id: U176-C1
worker: cascade
goal: U176 a user-window declaration behind Claude Code's leading system-reminder block still counts
inputs:
- v7_harness/coord/deliver.py sha256=b33924738f064d9e1f4fb1025557f44ed428a4badad921cf61e39bfc19608891
- v7_harness/coord/user_window.py sha256=65418faf6a6230da52e6145a9994c1d6049307c262cd3fa8027d6eb389fc1605
- v7_harness/coord/repeat_error.py sha256=2885a7e69c49f7048724691f858e08eb537f3bb5c015031c81770827b772449b
- tests/test_u176_reminder_prefixed_declaration.py sha256=7cce75678d610fe2914885e445dc450b179534b6e82ad74b334affe1812eb272
allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/user_window.py
- v7_harness/coord/repeat_error.py
acceptance: python -m unittest tests.test_u176_reminder_prefixed_declaration tests.test_u150_user_window tests.test_u163_desk_sync tests.test_u159_mixed_declaration tests.test_message_id_collision tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread tests.test_u120_agy_auto_reply tests.test_u127_agy_card_window tests.test_u131_agy_resume_cap tests.test_u134_dispatch_on_active tests.test_u134_f1b_cwd tests.test_u134_f2_queue_claim
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 150000
paid_after: U176-L1
paid_reason: deliver.py exceeds the local prompt cap
```

## Instructions for the worker

Card U176. Design audited by Antigravity: relay_5c7d751630eb5ae08a679338830260fa (PASS).

Problem: Claude Code puts its own `<system-reminder>...</system-reminder>` block in front of what the user typed
(first prompt of a desktop worktree session, 2026-10-10). `deliver.is_human_prompt` rejects any prompt whose first
non-space character is `<`, so `user_window.is_declaration` returned False and the window was never renamed.

Required change (three files, nothing else; do not rewrite files, edit in place):

1. `v7_harness/coord/deliver.py`, directly above `def is_human_prompt`:
   - a module-level compiled regex `_HARNESS_NOTE_RE` that matches, anchored at the very start of the string, one or
     more whole blocks `<system-reminder ...attributes optional...>` ... `</system-reminder>` (non-greedy, DOTALL),
     each optionally preceded by whitespace, plus the whitespace after the last block. A tag named
     `<system-reminders>` must not match; an unclosed block must not match.
   - `def typed_prompt(prompt: object) -> object:` returns the string with that leading match removed; a non-string
     is returned unchanged.
   - `is_human_prompt` judges `typed_prompt(prompt)` instead of `prompt`; its other conditions stay as they are.
   - a comment above the regex stating the receipt (U176, the date, why only whole leading blocks are dropped).
2. `v7_harness/coord/user_window.py`: import `typed_prompt` from `v7_harness.coord.deliver`; the first statement of
   `is_declaration` is `text = typed_prompt(text)`.
3. `v7_harness/coord/repeat_error.py`: import `typed_prompt` the same way; the first statement of `is_error_report`
   is `text = typed_prompt(text)`.

The tests in `tests/test_u176_reminder_prefixed_declaration.py` state the exact behaviour; do not edit any test.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
