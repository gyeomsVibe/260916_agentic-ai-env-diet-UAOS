```contract
work_id: U103-O1R
worker: apply
goal: olla hook-shell refuses a whole-file print of 8,000+ tokens on Codex PreToolUse, like Antigravity's olla-guard (rerun of U103-O1: its acceptance also ran the installer test that U103-O2 satisfies).
inputs:
- tests/test_u103_olla_parity.py sha256=a5baf93fa41515799fa2469f903eb5726cebe0480f87c17e30f97163cc0dd559
allow:
- v7_harness/olla.py
context_allow:
- tests/test_u103_olla_parity.py
acceptance: python -m unittest tests.test_u103_olla_parity.CodexShellDenyTests
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 18 lines). `olla hook-shell` on a Codex PreToolUse event refuses a whole-file print of >= 8,000 tokens and names the 0-token local route, the same gate Antigravity's olla-guard applies (U103-O). PostToolUse keeps its hint.

===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
def shell_read_hint(event: dict) -> str | None:
=======
def shell_read_deny(paths: list[Path]) -> str | None:
    """U103-O: the Codex PreToolUse deny line for a whole print of >= DENY_WHOLE_READ_TOKENS, like olla-guard's."""
    tokens = max((whole_read_tokens({"tool_input": {"file_path": str(p)}}) for p in paths), default=0)
    if tokens < DENY_WHOLE_READ_TOKENS:
        return None
    log_usage("deny_whole_read", tokens=tokens)
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                       "permissionDecisionReason": f"Whole-file read of ~{tokens:,} tokens refused; run `olla digest "
                       "<file>` or local_read_map (0 paid tokens), then print only the needed lines (`sed -n 'A,Bp'`)."}})


def shell_read_hint(event: dict) -> str | None:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
    base = Path(event.get("cwd") or ".")
    for raw in shell_read_targets(str(command)):
        path = Path(raw) if Path(raw).is_absolute() else base / raw
        hint = read_hint({"tool_input": {"file_path": str(path)}})
=======
    base = Path(event.get("cwd") or ".")
    paths = [Path(raw) if Path(raw).is_absolute() else base / raw for raw in shell_read_targets(str(command))]
    if event.get("hook_event_name") == "PreToolUse":
        return shell_read_deny(paths)
    for path in paths:
        hint = read_hint({"tool_input": {"file_path": str(path)}})
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
    if hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": hint}}, ensure_ascii=False))
=======
    if hint and event.get("hook_event_name") == "PreToolUse":
        print(hint)  # U103-O: already the whole PreToolUse deny
    elif hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": hint}}, ensure_ascii=False))
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
