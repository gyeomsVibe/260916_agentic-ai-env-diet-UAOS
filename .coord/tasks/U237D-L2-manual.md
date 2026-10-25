# U237D-L2: per-window suffix, adoption, UNKNOWN never BLOCKED, Claude repair line (desk_title.py, six whole functions)

Judge claude, deputy for LIMITED codex; Codex re-review owed. Card manual and fixed acceptance:
`.coord/tasks/U237D-card-manual.md`. Follows U237-A1 (version bump) and U237-L1R/L1B (user_window.py). Each
function is dictated verbatim; this slice runs the card's full fixed acceptance.

```contract
work_id: U237D-L2
worker: local
goal: the native title adapter shows each window's own topic, adopts a valid self-chosen one, never blocks on UNKNOWN readback, reads Claude's title from the transcript and adds the explicit Claude repair line from the second emit
inputs:
- v7_harness/coord/desk_title.py sha256=86a375db31a3d8ca7b91e3e17676e5fbd748056dc0f8a9e13c34295aa7a154af
- v7_harness/coord/user_window.py sha256=dd99bfac8fceb04354fcc7bef0cd2ce3e62877dd1922cdd83df72a2811bafcd8
- tests/test_u237_desk_titles.py sha256=5818f080d01c69c7f785837e0581aee727fbd8901e574e0ab84535af7078afee
allow:
- v7_harness/coord/desk_title.py
context_allow:
- v7_harness/coord/user_window.py
- tests/test_u237_desk_titles.py
acceptance: python -m unittest tests.test_u237_desk_titles tests.test_u207_desk_title_handoff tests.test_u229_independent_title tests.test_u229_title_worker tests.test_u234_title_consensus tests.test_u150_user_window
forbidden: editing or deleting tests; changing any other function; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: six whole top-level functions, verbatim

1. A new top-level function placed right after `_schedule_topic`:

```python
def _own_suffix(prefix: str, current: str | None, shared: str | None) -> str | None:
    """U237: a title the window gave itself (prefix, one space, a valid topic other than the shared fallback)."""
    from .title_consensus import valid_topic
    if not isinstance(current, str) or not current.startswith(prefix + " "):
        return None
    topic = current[len(prefix) + 1:]
    return topic if valid_topic(topic) and topic != shared else None
```

2. A new top-level function placed right after `_own_suffix`:

```python
def _desired_parts(project: Path, entry: dict, current: str | None) -> tuple[str | None, str | None]:
    """U237: (desired title, topic to adopt). The suffix is this window's own topic; the shared accepted topic is
    only a fallback for a window without one, so windows no longer all show one project-wide topic."""
    from .title_consensus import valid_topic
    raw = entry.get("title")
    match = uw.TITLE_RE.fullmatch(raw) if isinstance(raw, str) else None
    if not match:
        return None, None
    prefix = match.group(0)
    shared = _schedule_topic(project)
    own = entry.get("topic") if valid_topic(entry.get("topic")) else None
    adopted = None if own else _own_suffix(prefix, current, shared)
    topic = own or adopted or shared
    if topic:
        return f"{prefix} {topic}", adopted
    for prior in (entry.get("desired_title"), current):
        if isinstance(prior, str) and prior.startswith(prefix + " ") and prior.strip() == prior:
            if not any(unicodedata.category(c).startswith("C") for c in prior):
                return prior, None  # missing/stale consensus never strips an already accepted suffix
    return prefix, None
```

3. Replace the whole top-level function `_desired_title` with:

```python
def _desired_title(project: Path, entry: dict, current: str | None) -> str | None:
    return _desired_parts(project, entry, current)[0]
```

4. Replace the whole top-level function `_take_native` with:

```python
def _take_native(entry: dict, desired: str, current: str | None, adopted: str | None = None) -> str:
    if adopted and not entry.get("topic"):
        entry["topic"] = adopted  # U237: the window named itself; that topic is its own from now on
    if entry.get("adapter_version") != ADAPTER_VERSION or entry.get("desired_title") != desired:
        entry.update(adapter_version=ADAPTER_VERSION, desired_title=desired, native_emits=0,
                     converged=False, title_state="NATIVE_PENDING")
    if current == desired:
        entry.update(converged=True, title_state="NATIVE_CONFIRMED")
        return "CONVERGED"
    count = _emit_count(entry)
    if count >= MAX_NATIVE_EMITS:
        # U237: UNKNOWN readback (None) is no evidence of a failed rename; only a known other title blocks
        state = "BLOCKED" if current is not None else "UNVERIFIED"
        entry.update(converged=False, title_state=state)
        return state
    entry.update(native_emits=count + 1,
                 converged=False, title_state="NATIVE_PENDING")
    return "PENDING"
```

5. Replace the whole top-level function `_take_for_primary` with:

```python
def _take_for_primary(project: Path, tool: str, thread: str, entry: dict, desired: str,
                      current: str | None, adopted: str | None = None) -> str:
    # Called by _entry_change under the same registry lock used by claim/handoff.
    if uw.desk_role(project, tool, thread) != "PRIMARY":
        return "SKIPPED"
    return _take_native(entry, desired, current, adopted)
```

6. Replace the whole top-level function `reconcile_title` with:

```python
def reconcile_title(project: Path, tool: str, thread: str, event: dict) -> dict:
    empty = {"title": None, "instruction": "", "state": "SKIPPED"}
    if not _native_event(tool, thread, event) or uw.desk_role(project, tool, thread) != "PRIMARY":
        return empty
    record = _json(uw._presence(project) / "user_windows.json")
    entries = record.get(tool)
    if not isinstance(entries, list):
        return empty
    entry = next((e for e in entries if isinstance(e, dict) and e.get("thread") == thread), None)
    if entry is None:
        return empty
    if tool == "claude":
        current = event.get("session_title")
        if not isinstance(current, str):  # U237: the session transcript records the shown title
            current = uw._claude_title(thread, transcript=event.get("transcript_path"))
    else:
        current = uw._current_title(tool, thread)
    current = current if isinstance(current, str) else None
    desired, adopted = _desired_parts(Path(project), entry, current)
    if not desired:
        return empty
    seen = {}

    def take(e: dict) -> str:
        state = _take_for_primary(project, tool, thread, e, desired, current, adopted)
        seen["emits"] = _emit_count(e)
        return state

    state = uw._entry_change(project, tool, thread, take)
    title = desired if state == "PENDING" else None
    # U237: Claude's hook sessionTitle landed late; from the second emit the explicit tool call repairs it
    repair = tool != "claude" or seen.get("emits", 0) >= 2
    instruction = uw._instruction(project, tool, thread, desired, None) if title and repair else ""
    return {"title": title, "instruction": instruction, "state": state or "SKIPPED"}
```

## Output

- Reply with six ===EDIT blocks, each holding one whole top-level function above. No explanations. Do not claim
  success; the acceptance command decides.
