```contract
work_id: U176-L2
worker: local
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
context_allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/user_window.py
- v7_harness/coord/repeat_error.py
acceptance: python -m unittest tests.test_u176_reminder_prefixed_declaration tests.test_u150_user_window tests.test_u163_desk_sync tests.test_u159_mixed_declaration tests.test_message_id_collision tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread tests.test_u120_agy_auto_reply tests.test_u127_agy_card_window tests.test_u131_agy_resume_cap tests.test_u134_dispatch_on_active tests.test_u134_f1b_cwd tests.test_u134_f2_queue_claim
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U176. Design audited by Antigravity: relay_5c7d751630eb5ae08a679338830260fa (PASS).

Problem: Claude Code puts its own system-reminder block (an XML-like tag pair named system-reminder) in front of
what the user typed. The function `is_human_prompt` rejects any prompt whose first non-space character is "<", so a
real user-window declaration was ignored (2026-10-10).

Edit three files in place with small search/replace edits. Never rewrite a whole file. Never edit a test.

1. v7_harness/coord/deliver.py, directly above the function `is_human_prompt`, add:
   - a comment: U176, Claude Code prepends its own system-reminder blocks to a typed prompt; only whole leading
     blocks are dropped.
   - a module-level name _HARNESS_NOTE_RE = re.compile(r"\A(?:\s*<system-reminder(?:\s[^>]*)?>.*?</system-reminder>)+\s*", re.S)
   - a function named typed_prompt taking one argument named prompt (annotated object, returning object): when the
     argument is a str it returns _HARNESS_NOTE_RE.sub("", prompt), otherwise it returns the argument unchanged.
   Then make `is_human_prompt` start with the statement: prompt = typed_prompt(prompt)
   and keep its existing return line unchanged after it.
2. v7_harness/coord/user_window.py: change the import line that imports `is_human_prompt` so it also imports
   typed_prompt from the same module. In the function is_declaration add, as its first statement, before the line
   that calls `is_human_prompt`: text = typed_prompt(text)
3. v7_harness/coord/repeat_error.py: change the import line that imports `is_human_prompt` so it also imports
   typed_prompt. In the function is_error_report add, as its first statement, before the line that calls
   `is_human_prompt`: text = typed_prompt(text)


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
