```contract
work_id: U103-O2
worker: apply
goal: The installer wires the olla whole-read gates for Claude Code and Codex when olla is on PATH, leaving Antigravity's olla-guard untouched.
inputs:
- tests/test_u103_olla_parity.py sha256=a5baf93fa41515799fa2469f903eb5726cebe0480f87c17e30f97163cc0dd559
allow:
- v7_harness/global_install.py
context_allow:
- tests/test_u103_olla_parity.py
acceptance: python -m unittest tests.test_u103_olla_parity tests.test_u37_install_everywhere tests.test_u103_desk_delta
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 14 lines). When `olla` is on PATH, the installer adds the whole-read gate to Claude Code (PreToolUse Read → `olla hook-read`) and Codex (PreToolUse Bash → `olla hook-shell`; the matcher keeps other tool calls free of the ~0.5 s hook start), the gate that made Antigravity use the local model. Antigravity's own olla-guard group is not touched. The installer owns only these two exact commands, so a reinstall replaces them and an uninstall removes them.

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
HOOK_MARK = "coord presence"
=======
HOOK_MARK = "coord presence"
# U103-O: the olla whole-read gates the installer adds when `olla` is on PATH; only these exact commands are ours.
OLLA_HOOKS = ("olla hook-read", "olla hook-shell")
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
        hooks = [h for h in group["hooks"] if not (isinstance(h, dict) and HOOK_MARK in str(h.get("command", ""))
                                                   and "uaos.py" in str(h.get("command", "")))]
=======
        hooks = [h for h in group["hooks"] if not (isinstance(h, dict) and ((HOOK_MARK in str(h.get("command", ""))
                                                   and "uaos.py" in str(h.get("command", "")))
                                                   or h.get("command") in OLLA_HOOKS))]
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                after = _merge_hooks(data, wanted, uninstall)
                permissions = dict(after.get("permissions") or {})
=======
                if shutil.which("olla"):
                    wanted["PreToolUse"] = [{"matcher": "Read", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[0]}]}]
                after = _merge_hooks(data, wanted, uninstall)
                permissions = dict(after.get("permissions") or {})
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                changes.append(_json_change("codex hooks", path, data, _merge_hooks(data, wanted, uninstall),
=======
                if shutil.which("olla"):
                    wanted["PreToolUse"] = [{"matcher": "Bash", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[1]}]}]
                changes.append(_json_change("codex hooks", path, data, _merge_hooks(data, wanted, uninstall),
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
