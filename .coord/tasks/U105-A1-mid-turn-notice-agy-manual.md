```contract
work_id: U105-A1
worker: agy
goal: A letter or P1 that lands mid-turn reaches Claude, Codex and Antigravity at their next tool or model call (U105).
inputs:
- tests/test_u105_mid_turn_notice.py sha256=1571b19a73a227653c34ae0f473881b688b33980e361b72f198cec11ccd37d25
- v7_harness/cli.py sha256=bbcfb5b37618fef0bf7b41080655799c1b914d30372b9d7821a72bc3c5b2382b
- v7_harness/global_install.py sha256=97e9dd16c83b90e3f8b3153da6cb870676b202a9af78bb59471c62ac58c2f417
allow:
- v7_harness/cli.py
- v7_harness/global_install.py
acceptance: python -m unittest tests.test_u105_mid_turn_notice tests.test_u103_desk_delta tests.test_u103_olla_parity tests.test_u37_install_everywhere tests.test_u104_agy_sees_new_letters tests.test_u95a_antigravity_briefing
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1800
remote_budget_tokens: 1200000
```

## Instructions for the worker

You are the implementer for card U105. The judge (claude) wrote the acceptance test `tests/test_u105_mid_turn_notice.py` before this run; read it first. Do not edit any test.

Problem (receipt, 2026-10-01): each tool hears of new mailbox letters and P1 wakes only when the user types the next prompt. During a long autonomous turn a new verdict or P1 stays unseen, so the user pastes status lines between tools by hand.

Change exactly these two files, nothing else. Read them with grep and line ranges (both are long; do not read them whole): the functions named below are all you need.

1. `v7_harness/cli.py`
   a. In the `coord presence` parser (search `p_coord_presence.add_argument("--delta"`), add a flag `--post-tool` (store_true, default False). Help: "With --from-hook: print the line as PostToolUse JSON hookSpecificOutput.additionalContext (Claude, Codex mid-turn), nothing when there is no news (U105)".
   b. In `cmd_coord_presence`, inner function `_emit`: when `getattr(args, "post_tool", False)` is true, print `json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": line}}, ensure_ascii=False)` if `line` is non-empty, and print nothing otherwise (this must take precedence over every `say` mode). Plain stdout on PostToolUse never reaches the model; only this JSON does.
   c. In the `--delta` block of the same function, remove the condition `if event.get("invocationNum", 0) == 0:` so the delta is computed on every call (Antigravity's later model calls of a turn included). Keep the body. The delta cursor already makes a repeat silent. Update the comment to say U105 removed the first-call limit so a letter arriving mid-turn is heard at the next call.
   d. The mid-turn hooks pass `--tool` without `--state`; the existing `if args.tool and args.state:` already skips the presence write. Keep it.

2. `v7_harness/global_install.py`
   a. `presence_command(...)`: allow `state` to be `None`; when it is `None`, leave out `--state {state} --ttl {ttl}` and add ` --post-tool` at the end. Existing callers are unchanged.
   b. Claude block (`if tool == "claude":`, dict `wanted`): add `"PostToolUse": [{"hooks": [{"type": "command", "timeout": 10, "command": presence_command(python, launcher, "claude", None, 0, "p1", delta=True)}]}]` with no `matcher` (every Claude tool call). Comment: U105 mid-turn notice.
   c. Codex block (`elif tool == "codex":`, dict `wanted`): add `"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "timeout": 10, "command": presence_command(python, launcher, "codex", None, 0, "none", delta=True)}]}]`.
   d. Antigravity block: unchanged (its PreInvocation already runs on every model call; 1c covers it).

Record why next to each new value in a one-line comment, like the surrounding code. Keep the surrounding style (line length 120, type hints).

Check before you finish, from the repository root:
python -m unittest tests.test_u105_mid_turn_notice tests.test_u103_desk_delta tests.test_u103_olla_parity tests.test_u37_install_everywhere tests.test_u104_agy_sees_new_letters tests.test_u95a_antigravity_briefing
All must pass. If `tests.test_u103_desk_delta` fails only because it expects silence on a later Antigravity call, report that test name and stop; do not edit it.

Forbidden: editing tests, files outside the two allowed files, network, git commit/push, writing outside the staged copy you were given, reading whole files over 300 lines.


## Output

- Edit the files under `allow` directly with your file tools. Your reply is not applied: ===FILE / ===EDIT blocks in it are ignored. End with one line saying what you changed. Do not claim success; the acceptance command decides.
