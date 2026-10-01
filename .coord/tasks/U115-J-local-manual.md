```contract
work_id: U115-J
worker: local
goal: A Claude window letter resumes the window's full session id in the transcript's cwd
inputs:
- tests/test_u115_claude_full_session.py sha256=fe8ca385fbe3d34ff8181cbc7c5da7b5f5ca793bb8cb7821c82e6f1f7d11e2a3
- v7_harness/coord/windows.py sha256=98ae5bc251ac2e1d45a8431c9f61ec756cf3a22dba348b541cb4c21635aa1987
- v7_harness/coord/deliver.py sha256=3171b0039e4b8996d5f488f674729edc16557aa4cdb5c4a141affc787067eb76
allow:
- v7_harness/coord/windows.py
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u115_claude_full_session tests.test_u115_card_window_route tests.test_u114_windows
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Output SEARCH/REPLACE edits, one per `===EDIT: <path>=== ... ===END===` section. Edit only the two allowed files.

1. In `v7_harness/coord/windows.py`, add this function directly above `def window_for(` (add `import os` / `import json`
   to the imports: the module imports json but not os yet):

def claude_session(short: str) -> tuple[str, str]:
    """U115 judge: `claude --bg` prints an id prefix, but `--resume` needs the full id, and the transcript moves with a
    session that entered a worktree. Return (full id, latest cwd) from the one transcript `<prefix>*.jsonl` under
    `$CLAUDE_CONFIG_DIR` (default ~/.claude) `/projects/*/`; with none or several matches return (short, "")."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = sorted((home / "projects").glob(f"*/{short}*.jsonl"))
    if len(found) != 1:
        return short, ""
    cwd = ""
    with found[0].open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("cwd"):
                cwd = str(row["cwd"])
    return found[0].stem, cwd

2. In `v7_harness/coord/deliver.py`, inside `_deliver_to_claude_locked`, replace

    resume = False
    if session:  # U115: a card window is an existing session; the default delivery session file is left alone
        session_id, resume = session, True

   with

    resume = False
    window_cwd = ""
    if session:  # U115: a card window is an existing session; the default delivery session file is left alone
        from v7_harness.coord.windows import claude_session

        (session_id, window_cwd), resume = claude_session(session), True

3. In the same function replace

    if project_dir:
        kwargs["cwd"] = str(project_dir)

   with

    if project_dir:
        kwargs["cwd"] = str(project_dir)
    if window_cwd:  # U115 judge: resume where the window's transcript lives (it may have entered a worktree)
        kwargs["cwd"] = window_cwd

Change nothing else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
