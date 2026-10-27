# U266-L2 Contract Manual — Legacy Prefix Topic Extraction & Dynamic Self-Named Process Adoption in `desk_title.py`

```contract
work_id: U266-L2
worker: local
goal: Replace ADAPTER_VERSION, _own_suffix, and _desired_parts in v7_harness/coord/desk_title.py so legacy [사용자 대화창구-YYMMDD-N] self-named topics are normalized to [YYMMDD-N] <topic> and updated tool process topics are adopted across all 3 tools
inputs:
  - v7_harness/coord/desk_title.py sha256=c370806c60ffab56ff6f989c1cadeb56291c793e04627e1a5bc32c3f05b2ce7f
  - tests/test_u266_3tool_title_overhaul.py sha256=b37e771eb9440c5a32b3bed65fab31cd7b063d1464ebc94f6e61d841cd2bf7c9
allow:
  - v7_harness/coord/desk_title.py
context_allow:
  - tests/test_u266_3tool_title_overhaul.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u266_3tool_title_overhaul tests.test_u244_short_prefix_titles tests.test_u243_dynamic_process_titles tests.test_u237_desk_titles
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `ADAPTER_VERSION`, `def _own_suffix`, `def _desired_parts` only)

Replace `ADAPTER_VERSION`, `def _own_suffix`, and `def _desired_parts` in `v7_harness/coord/desk_title.py` with:

```python
ADAPTER_VERSION = "U266_UNIFIED1"  # U266: resets every desk's native budget once for 3-tool unified title overhaul


def _own_suffix(prefix: str, current: str | None, shared: str | None) -> str | None:
    """U237/U266: a title the window gave itself (short or legacy prefix, one space, a valid non-boilerplate topic)."""
    from .title_consensus import valid_topic
    if not isinstance(current, str):
        return None
    m = uw.TITLE_RE.match(current)
    if not m or f"[{m.group(1)}-{m.group(2)}]" != prefix or not current[m.end():].startswith(" "):
        return None
    topic = current[m.end() + 1:]
    return topic if valid_topic(topic) and not uw.is_boilerplate_topic(topic) and topic != shared else None


def _desired_parts(project: Path, entry: dict, current: str | None) -> tuple[str | None, str | None]:
    """U237/U243/U244/U266: (desired title, topic to adopt). Normalizes prefix to [YYMMDD-N] across all 3 tools."""
    from .title_consensus import valid_topic
    raw = entry.get("title")
    match = uw.TITLE_RE.fullmatch(raw) if isinstance(raw, str) else None
    if not match:
        return None, None
    prefix = f"[{match.group(1)}-{match.group(2)}]"
    shared = _schedule_topic(project)
    if shared and "shared_topic" in entry and shared != entry.get("shared_topic"):
        return f"{prefix} {shared}", shared
    raw_own = entry.get("topic")
    own = raw_own if (valid_topic(raw_own) and not uw.is_boilerplate_topic(raw_own)) else None
    self_named = None if current == entry.get("desired_title") else _own_suffix(prefix, current, shared)
    adopted = self_named if (self_named and self_named != own) else None
    topic = adopted or own or shared
    if topic:
        return f"{prefix} {topic}", adopted
    for prior in (entry.get("desired_title"), current):
        if isinstance(prior, str) and prior.startswith(prefix + " ") and prior.strip() == prior:
            if not any(unicodedata.category(c).startswith("C") for c in prior) and not uw.is_boilerplate_topic(prior[len(prefix) + 1:]):
                return prior, None  # missing/stale consensus never strips an already accepted suffix
    return prefix, None
```

Do not change any other line of the file.
