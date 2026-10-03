```contract
work_id: U131-L1
worker: apply
goal: the U127 resume cap holds for an Antigravity card window whose size was never recorded (U131)
inputs:
- .work/u131_apply.md sha256=640f28436b5100f1114eb45bdfaf574a9d71dc3c9d65c3ab38774a3be258b10e
allow:
- v7_harness/coord/windows.py
- v7_harness/coord/agy_dispatch.py
acceptance: python -m unittest tests.test_u131_agy_resume_cap tests.test_u127_agy_card_window tests.test_u120_agy_auto_reply tests.test_u114_windows tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u48_deliver tests.test_u49_dispatch_count
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: U131 exact apply: the resume cap holds for an Antigravity card window of unknown size

- Target files: `v7_harness/coord/agy_dispatch.py`, `v7_harness/coord/windows.py`

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
        if entry.get("id") and int(entry.get("last_input_tokens") or 0) < RESUME_MAX_INPUT:
=======
        tokens = entry.get("last_input_tokens")
        # U131: a window with no recorded size (opened by `coord window`) is unknown, never small: start fresh.
        if entry.get("id") and isinstance(tokens, int) and tokens < RESUME_MAX_INPUT:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
def _open_antigravity(project: Path, prompt: str, runner: Callable[..., Any]) -> str:
    done = runner([shutil.which("agy") or "agy", "-p", prompt, "--output-format", "json"], cwd=str(project),
                  capture_output=True, text=True, encoding="utf-8", timeout=AGY_TIMEOUT_S)
    return str(json.loads(done.stdout)["conversation_id"])
=======
def _open_antigravity(project: Path, prompt: str, runner: Callable[..., Any]) -> tuple[str, int | None]:
    done = runner([shutil.which("agy") or "agy", "-p", prompt, "--output-format", "json"], cwd=str(project),
                  capture_output=True, text=True, encoding="utf-8", timeout=AGY_TIMEOUT_S)
    envelope = json.loads(done.stdout)
    tokens = (envelope.get("usage") or {}).get("input_tokens")
    return str(envelope["conversation_id"]), tokens if isinstance(tokens, int) else None
>>>>>>> REPLACE

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
    name = window_title(card, title)
    if tool == "codex":
        window_id = _open_codex(project, name, prompt, rpc)
    elif tool == "claude":
        window_id = _open_claude(project, name, prompt, runner)
    else:
        window_id = _open_antigravity(project, prompt, runner)
    entry = {"id": window_id, "opened_at": time.time() if now is None else now}
=======
    name = window_title(card, title)
    extra: dict[str, Any] = {}
    if tool == "codex":
        window_id = _open_codex(project, name, prompt, rpc)
    elif tool == "claude":
        window_id = _open_claude(project, name, prompt, runner)
    else:
        window_id, tokens = _open_antigravity(project, prompt, runner)
        if tokens is not None:  # U131: the opening turn's size, so the U127 resume cap can read it
            extra["last_input_tokens"] = tokens
    entry = {"id": window_id, "opened_at": time.time() if now is None else now, **extra}
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
