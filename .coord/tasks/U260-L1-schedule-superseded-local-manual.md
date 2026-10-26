```contract
work_id: U260-L1
worker: local
goal: BLOCKED letters whose card the master schedule closed after the letter no longer enter the P1 wake
inputs:
- v7_harness/coord/sentinel.py sha256=0de0fbaa8f08a58ffdf2f40bbb9e29e01b597e4fb931d1a8b4b16bbf087593e8
allow:
- v7_harness/coord/sentinel.py
acceptance: python -m unittest tests.test_u260_schedule_superseded tests.test_u88_p1_superseded tests.test_u116_superseded_family
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/coord/sentinel.py. Make exactly two changes.

1. Directly after the function `_passed_since` (before `EXHAUSTED_SCHEMA = ...`), add this new function:

```python
_TERMINAL_PHASE_STATES = frozenset({"DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED"})


def _schedule_closed_since(project_root: Path, payload: dict[str, Any]) -> bool:
    """U260: the master schedule closed the letter's step, or its card (`U241C` for `U241C-S4`), after the letter.

    Most cards close through a merged PR, never a ledger PASS, so U88 alone kept 212 stale letters in every P1 wake.
    The phase's own `updated_at` is its close time, else the schedule's; no time, an open phase or an unreadable
    schedule keeps the alert.
    """
    from datetime import datetime

    step, stamp = payload.get("step"), payload.get("ts")
    if not isinstance(step, str) or not isinstance(stamp, str):
        return False
    try:
        blocked_at = datetime.fromisoformat(stamp).timestamp()
        schedule = json.loads((project_root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    phases = schedule.get("phases") if isinstance(schedule, dict) else None
    if not isinstance(phases, list):
        return False
    card = re.match(r"U\d+[A-Za-z]?(?=-|$)", step)
    wanted = {step.upper(), card.group(0).upper()} if card else {step.upper()}
    for phase in phases:
        if not isinstance(phase, dict) or str(phase.get("phase_id", "")).upper() not in wanted:
            continue
        if phase.get("state") not in _TERMINAL_PHASE_STATES:
            continue
        closed = phase.get("updated_at") or schedule.get("updated_at")
        try:
            closed_at = float(closed) if isinstance(closed, (int, float)) and not isinstance(closed, bool) \
                else datetime.fromisoformat(str(closed)).timestamp()
        except ValueError:
            continue
        if closed_at > blocked_at:
            return True
    return False
```

2. In `run_sentinel_cycle`, replace this exact line:

```python
        if payload.get("kind") == "BLOCKED" and not payload.get("is_p1") and _passed_since(passed, payload):
```

with:

```python
        if payload.get("kind") == "BLOCKED" and not payload.get("is_p1") and (
            _passed_since(passed, payload) or _schedule_closed_since(project_root, payload)
        ):
```

`json`, `re`, `Path` and `Any` are already imported at module top. Change nothing else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
