```contract
work_id: U103-A2R
worker: apply
goal: The installer adds --delta to each tool's per-prompt hook so every UAOS project gets the desk delta (rerun of U103-A2, whose stage predated Antigravity's note write).
inputs:
- tests/test_u103_desk_delta.py sha256=e3c9a829f3c3177f98739df30654216616b4d2c87dd3804018ab2d0086164d1c
allow:
- v7_harness/global_install.py
context_allow:
- tests/test_u103_desk_delta.py
acceptance: python -m unittest tests.test_u103_desk_delta tests.test_u37_install_everywhere
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 8 lines). The installer adds `--delta` to each tool's per-prompt hook (Claude UserPromptSubmit, Codex UserPromptSubmit, Antigravity PreInvocation), so every UAOS project on this machine gets the U103 desk delta without a project-bound script.

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
def presence_command(python: str, launcher: Path, tool: str, state: str, ttl: int, say: str) -> str:
    return (f"{uaos_command(python, launcher)} coord presence --tool {tool} --state {state} --ttl {ttl} "
            f"--from-hook --say {say}")
=======
def presence_command(python: str, launcher: Path, tool: str, state: str, ttl: int, say: str,
                     delta: bool = False) -> str:
    # U103: `delta` adds what the other tools changed since this tool last looked (per-prompt hooks only).
    return (f"{uaos_command(python, launcher)} coord presence --tool {tool} --state {state} --ttl {ttl} "
            f"--from-hook --say {say}" + (" --delta" if delta else ""))
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                        python, launcher, "claude", "ACTIVE", 3600, "p1")}]}],
=======
                        python, launcher, "claude", "ACTIVE", 3600, "p1", delta=True)}]}],
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                        python, launcher, "codex", "ACTIVE", 3600, "none")}]}],
=======
                        python, launcher, "codex", "ACTIVE", 3600, "none", delta=True)}]}],
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
                        python, launcher, "antigravity", "ACTIVE", 3600, "agy")}]}
=======
                        python, launcher, "antigravity", "ACTIVE", 3600, "agy", delta=True)}]}
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
