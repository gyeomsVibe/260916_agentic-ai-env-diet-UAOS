# U237-L1B: per-window topic, full-title prefix-era path, UNKNOWN never BLOCKED (user_window.py, five whole functions)

Judge claude, deputy for LIMITED codex; Codex re-review owed. Card manual and fixed acceptance:
`.coord/tasks/U237-card-manual.md`. Follows U237-L1R (readback, `_shows`). Each function is dictated verbatim.

```contract
work_id: U237-L1B
worker: local
goal: a declaration stores the window's own topic, the prefix-era path compares the full title and leaves native desks alone, and UNKNOWN readback alone never blocks
inputs:
- v7_harness/coord/user_window.py sha256=da6682fa52145c0452cd4dd2353752002d9bdc856a4817dd0e4027bf9fa09ac7
- tests/test_u237_desk_titles.py sha256=5818f080d01c69c7f785837e0581aee727fbd8901e574e0ab84535af7078afee
allow:
- v7_harness/coord/user_window.py
context_allow:
- tests/test_u237_desk_titles.py
acceptance: python -m unittest tests.test_u237_desk_titles.PerWindowTopic.test_topic_from_declaration tests.test_u150_user_window tests.test_u207_desk_title_handoff tests.test_u229_independent_title tests.test_u229_title_worker
forbidden: editing or deleting tests; changing any other function; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: five whole top-level functions, verbatim

1. A new top-level function placed right after `_shows`:

```python
def _topic_from_text(text) -> str | None:
    """U237: a window's own sidebar topic is the first sentence of its declaration prompt that is not the declaration,
    with URLs, paths and brackets removed, cut at a word to the topic limit. None when nothing valid remains."""
    from .title_consensus import MAX_TOPIC_CHARS, valid_topic
    text = typed_prompt(text)
    if not isinstance(text, str):
        return None
    for sentence in re.split(r"[\n.!?。]+", text):
        if _DECLARE_RE.search(sentence) and any(word in sentence for word in _DESIGNATION):
            continue
        words = re.sub(r"https?://\S*|[A-Za-z]:[\\/]\S*|\S*[\\/]\S*|[\[\]]", " ", sentence).split()
        topic = ""
        for word in words:
            if len(f"{topic} {word}".strip()) > MAX_TOPIC_CHARS:
                break
            topic = f"{topic} {word}".strip()
        topic = topic or (words[0][:MAX_TOPIC_CHARS] if words else "")
        if len(topic) >= 2 and valid_topic(topic):
            return topic
    return None
```

2. A new top-level function placed right after `_topic_from_text`:

```python
def _full_title(project: Path, entry, current: str | None) -> str | None:
    """U237: the full desired title (prefix plus this window's topic) by the native adapter's rule."""
    from .desk_title import _desired_title  # desk_title imports this module; a call-time import avoids the cycle
    return _desired_title(Path(project), entry, current) if isinstance(entry, dict) else None
```

3. Replace the whole top-level function `_take_emit` with:

```python
def _take_emit(entry: dict, known: bool = True) -> bool:
    """One emit from the bounded budget; concurrent hooks count under the lock, so the cap holds in parallel.
    U237: an exhausted budget is BLOCKED only after a known other title; UNKNOWN readback alone is UNVERIFIED."""
    if entry.get("converged"):
        return False
    if int(entry.get("emits") or 0) >= MAX_EMITS:
        entry["title_state"] = "BLOCKED" if known else "UNVERIFIED"
        return False
    entry["emits"] = int(entry.get("emits") or 0) + 1
    entry["title_state"] = "PENDING"
    return True
```

4. Replace the whole top-level function `reconcile` with:

```python
def reconcile(project: Path, tool: str, thread: str, *, now: datetime | None = None) -> str:
    """U207: on every real prompt of a claimed desk, re-issue the rename until the tool's own store shows it.
    A lost hook output (timeout, dropped line) is therefore repaired by the next prompt, not lost for good.
    U237: the full title is compared, and a desk the native adapter manages (`adapter_version`) is left to
    desk_title.reconcile_title; this path, run on relay prompts too, converged Codex 01a17325 on its prefix."""
    try:
        record = json.loads((_presence(project) / "user_windows.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    entry = next((e for e in (record.get(tool) or []) if e.get("thread") == thread), None) \
        if isinstance(record, dict) else None
    if not entry or entry.get("converged") or entry.get("title_state") == "BLOCKED" or entry.get("adapter_version"):
        return ""  # converged desks cost no readback at all
    if desk_role(project, tool, thread) == "HANDED_OFF":
        return ""  # U207-B: a handed-off desk keeps its title and gets no rename duty
    current = _current_title(tool, thread)
    title = _full_title(project, entry, current) or entry["title"]
    if _shows(current, title):
        _entry_change(project, tool, thread, _converge)
        return ""
    if not _entry_change(project, tool, thread, lambda e: _take_emit(e, current is not None)):
        return ""
    return _instruction(project, tool, thread, title, now)
```

5. Replace the whole top-level function `on_prompt` with:

```python
def on_prompt(project: Path, tool: str, thread: str, prompt, *, now: datetime | None = None,
              current: str | None = None) -> str:
    if not thread:
        return ""
    if not is_declaration(prompt):
        return reconcile(project, tool, thread, now=now)
    current = current if current is not None else _current_title(tool, thread)
    existing = _codex_names() if tool == "codex" else []
    got = claim(project, tool, thread, now=now, existing=existing, current=current)
    topic = _topic_from_text(prompt)

    def own(entry: dict) -> dict:  # U237: only this window's own declaration sets its topic, and only once
        if topic and not entry.get("topic"):
            entry["topic"] = topic
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

## Output

- Reply with five ===EDIT blocks, each holding one whole top-level function above. No explanations. Do not claim
  success; the acceptance command decides.
