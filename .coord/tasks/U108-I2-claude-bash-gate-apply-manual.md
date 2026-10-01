```contract
work_id: U108-I2
worker: apply
goal: Claude Code's Bash gets the same olla shell gate Codex has, so a whole print of a big file is refused with its outline like a whole Read
inputs:
- v7_harness/global_install.py sha256=7ac63af963cb917c6dc2ae140c4020d7e70dea3b46fc4a5cbde9a60fad102705
- tests/test_u108_map_first.py sha256=b1c1453adf331b6c0e9c210537235bea4d2f8c8f48c3aaba01a9538c20040e30
allow:
- v7_harness/global_install.py
acceptance: python -m unittest tests.test_u108_map_first tests.test_u37_install_everywhere tests.test_u107_plan_hook_install tests.test_u103_olla_parity tests.test_u45_general_uaos tests.test_u87_uaos_rsi_name tests.test_u90_canon_note tests.test_u91_stale_sentinel_task
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly.

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                    wanted["PreToolUse"] = [{"matcher": "Read", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[0]}]}]
=======
                    # U108: Claude's Bash gets Codex's shell gate; `cat big.py` used to pass where Read was refused.
                    wanted["PreToolUse"] = [
                        {"matcher": "Bash", "hooks": [{"type": "command", "timeout": 10, "command": OLLA_HOOKS[1]}]},
                        {"matcher": "Read", "hooks": [{"type": "command", "timeout": 10, "command": OLLA_HOOKS[0]}]}]
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
