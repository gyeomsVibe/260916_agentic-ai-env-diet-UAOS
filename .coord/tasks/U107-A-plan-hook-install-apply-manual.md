```contract
work_id: U107-A
worker: apply
goal: Wire olla hook-plan on UserPromptSubmit for Claude and Codex in the installer when olla is installed (removed on uninstall) and drop the retired '- 과정' report line from PLAN_HINT.
inputs:
- v7_harness/global_install.py sha256=04349f85a82d88a560f9af8975eae33a2a102e1143b7e226ccac528c96388380
- v7_harness/olla.py sha256=d8dcf0f100e2ab333c373fe20be0667d4595acc8dec0a22c3d241f2c56084747
- tests/test_u107_plan_hook_install.py sha256=3898a2dc7cb3d9b1d9908d2cc15aa3d44562139bacb95778e16aa07faa750fa5
allow:
- v7_harness/global_install.py
- v7_harness/olla.py
acceptance: python -m unittest tests.test_u107_plan_hook_install tests.test_u103_olla_parity tests.test_u37_install_everywhere tests.test_u17_olla tests.test_u92_tool_configs_brief_ko tests.test_u45_general_uaos tests.test_u47_d1_local_usage tests.test_u87_uaos_rsi_name tests.test_u90_canon_note tests.test_u91_stale_sentinel_task
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1200
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly.

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
OLLA_HOOKS = ("olla hook-read", "olla hook-shell")
=======
# U107: hook-plan is the per-prompt split hint Antigravity gets from `olla hook-agy PreInvocation`.
OLLA_HOOKS = ("olla hook-read", "olla hook-shell", "olla hook-plan")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                    wanted["PreToolUse"] = [{"matcher": "Read", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[0]}]}]
=======
                    wanted["PreToolUse"] = [{"matcher": "Read", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[0]}]}]
                    wanted["UserPromptSubmit"].append({"hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[2]}]})
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                    wanted["PreToolUse"] = [{"matcher": "Bash", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[1]}]}]
=======
                    wanted["PreToolUse"] = [{"matcher": "Bash", "hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[1]}]}]
                    wanted["UserPromptSubmit"].append({"hooks": [
                        {"type": "command", "timeout": 10, "command": OLLA_HOOKS[2]}]})
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
    "Report: no text between tool calls; end in Korean with `**결과**:` / `- 과정: A → B → C` / `- 근거:` / "
=======
    "Report: no text between tool calls; end in Korean with `**결과**:` / `- 근거:` / "
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
