# U243-L2 Contract Manual — `_take_native` and `_desired_parts` dynamic process topic transition and stale desired_title guard

```contract
work_id: U243-L2
worker: local
goal: Replace _take_native and _desired_parts in v7_harness/coord/desk_title.py so schedule topic changes dynamically update entry["topic"] and entry["shared_topic"] across all 3 tools and stale desired_title is not falsely adopted as own topic
inputs:
  - v7_harness/coord/desk_title.py sha256=c104889ed71c9ee1e7e5538eb1775f07c1e3049901efca31bbfc80ae797b8ee0
  - tests/test_u243_dynamic_process_titles.py sha256=fa77f9998384a140e3cc35164fe4668daf25e00adebc6f94af83edb49d76bb06
allow:
  - v7_harness/coord/desk_title.py
context_allow:
  - tests/test_u243_dynamic_process_titles.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u243_dynamic_process_titles tests.test_u237_desk_titles tests.test_u229_independent_title tests.test_u229_title_worker
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `def _take_native` and `def _desired_parts` only)

Replace the whole functions `_take_native` and `_desired_parts` in `v7_harness/coord/desk_title.py` with:

```python
def _take_native(entry: dict, desired: str, current: str | None, adopted: str | None = None) -> str:
    if adopted:
        entry["topic"] = adopted  # U237/U243: self-named or updated schedule topic becomes this window's topic
        if "shared_topic" in entry:
            entry["shared_topic"] = adopted
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


def _desired_parts(project: Path, entry: dict, current: str | None) -> tuple[str | None, str | None]:
    """U237/U243: (desired title, topic to adopt). When the shared schedule topic changes after declaration,
    transition to the new process topic; otherwise keep own topic and guard stale desired_title from false adoption."""
    from .title_consensus import valid_topic
    raw = entry.get("title")
    match = uw.TITLE_RE.fullmatch(raw) if isinstance(raw, str) else None
    if not match:
        return None, None
    prefix = match.group(0)
    shared = _schedule_topic(project)
    if shared and "shared_topic" in entry and shared != entry.get("shared_topic"):
        return f"{prefix} {shared}", shared
    own = entry.get("topic") if valid_topic(entry.get("topic")) else None
    adopted = None if (own or current == entry.get("desired_title")) else _own_suffix(prefix, current, shared)
    topic = own or adopted or shared
    if topic:
        return f"{prefix} {topic}", adopted
    for prior in (entry.get("desired_title"), current):
        if isinstance(prior, str) and prior.startswith(prefix + " ") and prior.strip() == prior:
            if not any(unicodedata.category(c).startswith("C") for c in prior):
                return prior, None  # missing/stale consensus never strips an already accepted suffix
    return prefix, None
```

Do not change any other line of the file.
