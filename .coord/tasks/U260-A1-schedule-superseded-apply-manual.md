```contract
work_id: U260-A1
worker: apply
goal: BLOCKED letters whose card the master schedule closed after the letter no longer enter the P1 wake.
apply_after: U260-L1
inputs:
- v7_harness/coord/sentinel.py sha256=5bcc7023d7e44166b1224b397fa107e982c4428af6cdc0be03501158396041c3
- tests/test_u260_schedule_superseded.py sha256=91224eec932c5a4fec5fb842fbac18a961d31154c4e888e5822b623da8bc5fb9
allow:
- v7_harness/coord/sentinel.py
acceptance: python -m unittest tests.test_u260_schedule_superseded tests.test_u88_p1_superseded tests.test_u116_superseded_family
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. Ollama U260-L1 wrote the function but placed it at file end and skipped the call site
(acceptance 1 failure); Haiku 5.5 rescue U260-H1 produced this text, which passes the acceptance (12 OK).

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
EXHAUSTED_SCHEMA = "u190b-exhausted-v1"
=======
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


EXHAUSTED_SCHEMA = "u190b-exhausted-v1"
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        if payload.get("kind") == "BLOCKED" and not payload.get("is_p1") and _passed_since(passed, payload):
=======
        if payload.get("kind") == "BLOCKED" and not payload.get("is_p1") and (
            _passed_since(passed, payload) or _schedule_closed_since(project_root, payload)
        ):
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
