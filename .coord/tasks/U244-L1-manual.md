# U244-L1 Contract Manual — `[YYMMDD-N]` short title prefix across all 3 tools in `user_window.py`

```contract
work_id: U244-L1
worker: local
goal: Replace TITLE_PREFIX, TITLE_RE, is_declaration, claim, and _codex_names in v7_harness/coord/user_window.py so user-facing windows use the [YYMMDD-N] prefix and automatically migrate legacy [사용자 대화창구-YYMMDD-N] titles
inputs:
  - v7_harness/coord/user_window.py sha256=f89fdf93e06313f8527d5dbcaa9e9ab61e839b6d665727190bec0d8d31a34697
  - tests/test_u244_short_prefix_titles.py sha256=f69f7feee1977a6c05fc2dcbcd2b9e74de6cabc807fa15562919d96052359f55
allow:
  - v7_harness/coord/user_window.py
context_allow:
  - tests/test_u244_short_prefix_titles.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u150_user_window
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `TITLE_PREFIX`, `TITLE_RE`, `def is_declaration`, `def claim`, `def _codex_names` only)

Replace `TITLE_PREFIX`, `TITLE_RE`, `def is_declaration`, `def claim`, and `def _codex_names` in `v7_harness/coord/user_window.py` with:

```python
TITLE_PREFIX = "["
TITLE_RE = re.compile(r"\[(?:사용자 대화창구-)?(\d{6})-(\d+)\]")


def is_declaration(text) -> bool:
    text = typed_prompt(text)  # U176: the harness's own leading reminder is not what was typed
    if not is_human_prompt(text) or "대화창구" not in text or "[사용자 대화창구-" in text or TITLE_RE.search(text):
        return False  # a "[YYMMDD-N]" or "[사용자 대화창구-…]" mention refers to an existing window, it does not open one
    # U159: one prompt can declare the window and then list requirements that name errors (Codex relay_89ccebf3);
    # a declaration is one sentence, so a repair word only rejects the sentence it is in.
    for sentence in re.split(r"[\n.!?。]+", text):
        if (_DECLARE_RE.search(sentence) and any(word in sentence for word in _DESIGNATION)
                and not any(word in sentence.lower() for word in _REPAIR)):
            return True
    return False


def claim(project: Path, tool: str, thread: str, *, now: datetime | None = None,
          existing: list[str] | None = None, current: str | None = None) -> dict:
    """`current` is the thread's title in its own tool; a permanent one is bound as [YYMMDD-N], never renumbered."""
    folder = _presence(project)
    folder.mkdir(parents=True, exist_ok=True)
    record_path, lock = folder / "user_windows.json", folder / "user_windows.lock"
    from contextlib import ExitStack
    from .stream import _exclusive
    stack = ExitStack()
    stack.enter_context(_exclusive(lock))
    try:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        record = record if isinstance(record, dict) else {}
        entries = record.setdefault(tool, [])
        for entry in entries:
            if entry.get("thread") == thread:
                m = TITLE_RE.search(str(entry.get("title") or ""))
                if m:
                    entry["title"] = f"[{m.group(1)}-{m.group(2)}]"
                _mark_primary(entries, entry)  # U207-B: a fresh declaration makes this window the primary again
                _save(record_path, record)
                return {"title": entry["title"], "new": False, "tool": tool, "thread": thread}
        date = (now or datetime.now()).strftime("%y%m%d")
        kept = TITLE_RE.search(current or "")
        numbers = [0]
        for title in [e.get("title", "") for e in entries] + list(existing or []):
            match = TITLE_RE.search(title or "")
            if match and match.group(1) == date:
                numbers.append(int(match.group(2)))
        title = f"[{kept.group(1)}-{kept.group(2)}]" if kept else f"[{date}-{max(numbers) + 1}]"
        entries.append({"thread": thread, "title": title, "date": kept.group(1) if kept else date, "at": time.time()})
        _mark_primary(entries, entries[-1])
        _save(record_path, record)
        return {"title": title, "new": not kept, "tool": tool, "thread": thread}
    finally:
        stack.close()


def _codex_names() -> list[str]:
    """Read-only (`mode=ro`): today's existing Codex titles seed the number so Codex's hand-made -1, -2 continue."""
    try:
        con = sqlite3.connect(f"{_codex_db().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            return [row[0] for row in con.execute(
                "SELECT name FROM threads WHERE name LIKE '[%'") if row[0] and TITLE_RE.search(row[0])]
        finally:
            con.close()
    except sqlite3.Error:
        return []
```

Do not change any other line of the file.
