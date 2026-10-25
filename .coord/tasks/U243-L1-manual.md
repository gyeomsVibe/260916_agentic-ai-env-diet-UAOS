# U243-L1 Contract Manual — `on_prompt` records `shared_topic` baseline on declaration and guards `QUIET_LOCK`

```contract
work_id: U243-L1B
worker: local
goal: Replace on_prompt in v7_harness/coord/user_window.py so declaration records entry["shared_topic"] from _schedule_topic(Path(project)), updates entry["topic"] when prompt has a topic, and skips auto_render_control_ux when .work/QUIET_LOCK exists
inputs:
  - v7_harness/coord/user_window.py sha256=a7ea1bbc5a82338deadde9c9ff79c31f3e5e359eb25e42d278444a68e5930a31
  - tests/test_u243_dynamic_process_titles.py sha256=fa77f9998384a140e3cc35164fe4668daf25e00adebc6f94af83edb49d76bb06
allow:
  - v7_harness/coord/user_window.py
context_allow:
  - tests/test_u243_dynamic_process_titles.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u150_user_window
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `def on_prompt` only)

Replace the whole function `on_prompt` in `v7_harness/coord/user_window.py` with:

```python
def on_prompt(project: Path, tool: str, thread: str, prompt, *, now: datetime | None = None,
              current: str | None = None) -> str:
    if not thread:
        return ""
    try:
        if not (Path(project) / ".work" / "QUIET_LOCK").is_file():
            from v7_harness.control_ux import auto_render_control_ux
            auto_render_control_ux(project, tool, str(prompt or ""))
    except Exception:
        pass
    if not is_declaration(prompt):
        return reconcile(project, tool, thread, now=now)
    current = current if current is not None else _current_title(tool, thread)
    existing = _codex_names() if tool == "codex" else []
    got = claim(project, tool, thread, now=now, existing=existing, current=current)
    topic = _topic_from_text(prompt)
    from .desk_title import _schedule_topic
    shared_now = _schedule_topic(Path(project)) or ""

    def own(entry: dict) -> dict:  # U237/U243: declaration records own topic and current shared_topic baseline
        if topic:
            entry["topic"] = topic
        entry["shared_topic"] = shared_now
        return dict(entry)

    title = _full_title(project, _entry_change(project, tool, thread, own), current) or got["title"]
    if _shows(current, title):
        _entry_change(project, tool, thread, _converge)
        return ""  # the window already shows its permanent title; nothing to rename

    def restart(entry: dict) -> bool:  # a fresh declaration opens a fresh bounded budget
        entry.update(converged=False, emits=0, native_emits=0, title_state="PENDING")
        return _take_emit(entry, current is not None)

    _entry_change(project, tool, thread, restart)
    return _instruction(project, tool, thread, title, now)
```

Do not change any other line of the file.
