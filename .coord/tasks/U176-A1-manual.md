```contract
work_id: U176-A1
worker: apply
apply_after: U176-L1
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
acceptance: python -m unittest tests.test_u176_reminder_prefixed_declaration tests.test_u150_user_window tests.test_u163_desk_sync tests.test_u159_mixed_declaration tests.test_message_id_collision tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U176 (a user-window declaration typed behind Claude Code's own leading `<system-reminder>` block still counts).
Design audited by Antigravity: relay_5c7d751630eb5ae08a679338830260fa (PASS). Dictation: copy the five edit blocks
below exactly, in this order, and change nothing else. Do not rewrite any file.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def is_human_prompt(prompt: object) -> bool:
    return isinstance(prompt, str) and bool(prompt.strip()) and not prompt.lstrip().startswith(INJECTED_PREFIXES)
=======
# U176: Claude Code puts its own `<system-reminder>…</system-reminder>` blocks in front of what 윤겸스 typed (the
# first prompt of a desktop worktree session, 2026-10-10), and the "<" injected prefix then hid a real declaration.
# Only whole leading blocks are dropped (tag attributes allowed, Antigravity audit relay_6c7083d0); a prompt that is
# nothing but a reminder stays empty, so not human.
_HARNESS_NOTE_RE = re.compile(r"\A(?:\s*<system-reminder(?:\s[^>]*)?>.*?</system-reminder>)+\s*", re.S)


def typed_prompt(prompt: object) -> object:
    return _HARNESS_NOTE_RE.sub("", prompt) if isinstance(prompt, str) else prompt


def is_human_prompt(prompt: object) -> bool:
    prompt = typed_prompt(prompt)
    return isinstance(prompt, str) and bool(prompt.strip()) and not prompt.lstrip().startswith(INJECTED_PREFIXES)
>>>>>>> REPLACE

===EDIT: v7_harness/coord/user_window.py===
<<<<<<< SEARCH
from v7_harness.coord.deliver import is_human_prompt
=======
from v7_harness.coord.deliver import is_human_prompt, typed_prompt
>>>>>>> REPLACE

===EDIT: v7_harness/coord/user_window.py===
<<<<<<< SEARCH
def is_declaration(text) -> bool:
=======
def is_declaration(text) -> bool:
    text = typed_prompt(text)  # U176: the harness's own leading reminder is not what was typed
>>>>>>> REPLACE

===EDIT: v7_harness/coord/repeat_error.py===
<<<<<<< SEARCH
from v7_harness.coord.deliver import is_human_prompt
=======
from v7_harness.coord.deliver import is_human_prompt, typed_prompt
>>>>>>> REPLACE

===EDIT: v7_harness/coord/repeat_error.py===
<<<<<<< SEARCH
def is_error_report(text) -> bool:
=======
def is_error_report(text) -> bool:
    text = typed_prompt(text)  # U176
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
