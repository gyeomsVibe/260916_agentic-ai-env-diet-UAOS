# U244-L2 Contract Manual — `[YYMMDD-N] <프로세스명>` normalization in `desk_title.py`

```contract
work_id: U244-L2
worker: local
goal: Replace ADAPTER_VERSION, _take_native, and _desired_parts in v7_harness/coord/desk_title.py so all 3 tools normalize prefix to [YYMMDD-N] and transition to [YYMMDD-N] <프로세스명>
inputs:
  - v7_harness/coord/desk_title.py sha256=581f23cd9134b1f5691459b4677c7a87be91db4fc70dcc139036da538246b93f
  - tests/test_u244_short_prefix_titles.py sha256=f69f7feee1977a6c05fc2dcbcd2b9e74de6cabc807fa15562919d96052359f55
allow:
  - v7_harness/coord/desk_title.py
context_allow:
  - tests/test_u244_short_prefix_titles.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u244_short_prefix_titles tests.test_u243_dynamic_process_titles tests.test_u237_desk_titles tests.test_u229_independent_title tests.test_u229_title_worker
forbidden: editing or deleting tests; edits outside allow; edits to any other function; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `ADAPTER_VERSION`, `def _take_native`, and `def _desired_parts` only)

Replace `ADAPTER_VERSION`, `def _take_native`, and `def _desired_parts` in `v7_harness/coord/desk_title.py` with:

```python
ADAPTER_VERSION = "U244_SHORT1"  # U244: resets every desk's native budget once to transition to [YYMMDD-N]


def _take_native(entry: dict, desired: str, current: str | None, adopted: str | None = None) -> str:
    m = uw.TITLE_RE.fullmatch(str(entry.get("title") or ""))
    if m:
        entry["title"] = f"[{m.group(1)}-{m.group(2)}]"
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
    """U237/U243/U244: (desired title, topic to adopt). Normalizes prefix to [YYMMDD-N] across all 3 tools."""
    from .title_consensus import valid_topic
    raw = entry.get("title")
    match = uw.TITLE_RE.fullmatch(raw) if isinstance(raw, str) else None
    if not match:
        return None, None
    prefix = f"[{match.group(1)}-{match.group(2)}]"
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
