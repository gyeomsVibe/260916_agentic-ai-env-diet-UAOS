# U237-L1: Claude transcript readback and full-title comparison (user_window.py, three whole functions)

Judge claude, deputy for LIMITED codex; Codex re-review owed. Card manual and fixed acceptance:
`.coord/tasks/U237-card-manual.md`. The splicer replaces or adds whole top-level functions; each function below
is dictated verbatim.

```contract
work_id: U237-L1
worker: local
goal: Claude desk title readback comes from the session transcript and convergence needs the full title
inputs:
- v7_harness/coord/user_window.py sha256=69236c4f34fe948b751973292235b3930d0330ef465c60077b061b9e4e718e1c
- tests/test_u237_desk_titles.py sha256=5818f080d01c69c7f785837e0581aee727fbd8901e574e0ab84535af7078afee
allow:
- v7_harness/coord/user_window.py
context_allow:
- tests/test_u237_desk_titles.py
acceptance: python -m unittest tests.test_u237_desk_titles.ClaudeReadback.test_transcript_custom_title_is_the_readback tests.test_u150_user_window tests.test_u229_independent_title tests.test_u229_title_worker
forbidden: editing or deleting tests; changing any other function; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: three whole top-level functions, verbatim

1. A new top-level function placed right after `_claude_sessions_root`:

```python
def _claude_transcript_title(thread: str, transcript, *, tail: int = 4 << 20) -> str | None:
    """U237: the session's last `custom-title` record in its own transcript. Claude Code re-appends it every turn
    (82 times in desk 46c52914), so a 4 MiB tail holds it. Any read or parse failure is UNKNOWN (None)."""
    try:
        with Path(transcript).open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - tail))
            text = handle.read().decode("utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    for line in reversed(text.splitlines()):
        if '"custom-title"' not in line or thread not in line:
            continue  # cheap filter: most lines are not this session's title record
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "custom-title" and data.get("sessionId") == thread:
            title = data.get("customTitle")
            return title if isinstance(title, str) else None
    return None
```

2. Replace the whole top-level function `_claude_title` with:

```python
def _claude_title(thread: str, *, root: Path | None = None, transcript=None) -> str | None:
    """Read-only. U237: the session transcript first (the MSIX desktop app moved its session store out of the hook's
    reach, so that read was UNKNOWN forever); the desktop app's per-session JSON stays the second source."""
    if thread and transcript:
        title = _claude_transcript_title(thread, transcript)
        if title is not None:
            return title
    folder = Path(root) if root else _claude_sessions_root()
    if not thread or not folder.is_dir():
        return None
    for path in folder.glob("*/*/local_*.json"):
        try:
            text = path.read_text(encoding="utf-8")
            if thread not in text:
                continue  # cheap filter: most files never mention this session
            data = json.loads(text)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("cliSessionId") == thread:
            title = data.get("title")
            return title if isinstance(title, str) else None
    return None
```

3. Replace the whole top-level function `_shows` with:

```python
def _shows(current: str | None, title: str) -> bool:
    """U237: the full title must show; a prefix-only name (Codex 01a17325) is not converged. None is UNKNOWN."""
    return isinstance(current, str) and bool(title) and current == title
```

## Output

- Reply with three ===EDIT blocks, each holding one whole top-level function above. No explanations. Do not
  claim success; the acceptance command decides.
