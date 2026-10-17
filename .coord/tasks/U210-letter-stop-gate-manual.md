```contract
work_id: U210-L2
worker: local
goal: In v7_harness/coord/stop_gate.py add the constants LETTER_FRESH_S and LETTER_NAMES, the functions pending_letters and letter_hold, and three lines in gate() that return letter_hold's hold, exactly as dictated below, so a turn end is held once while an ACTIONABLE letter addressed to the tool is still in the inbox. Change nothing else.
inputs:
- v7_harness/coord/stop_gate.py sha256=4040462281cc32310f144b3e738ae14a30ad27146544c8d0f87d676f5bc0ba8f
- tests/test_u210_letter_stop_gate.py sha256=8a3356c04ee7adc9c7c1c297ebc3cedfbccb595632f19783b12f89b3f8263cb7
allow:
- v7_harness/coord/stop_gate.py
acceptance: python -m unittest tests.test_u210_letter_stop_gate tests.test_u146a_next_card tests.test_u146b_auto_gates tests.test_u146a_r_ownership tests.test_u146a_r2_claim_lock
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

- Change only `v7_harness/coord/stop_gate.py`. Emit only whole top-level definitions (constants and complete `def`
  blocks), never a fragment of a function body. Copy the code below character for character.
- Retry note: run U210-L1 failed with SPLICE_UNSUPPORTED:Try because a `try:` fragment was emitted at top level. Emit
  the five definitions below and nothing else.

Definition 1 and 2 (new constants):

```python
# U210: a letter counts as processed only once `coord ack` moves it out of the inbox. The inbox backlog that predates
# this rule (1885 items on 2026-10-18) is not news, so only letters younger than one day hold a stop.
LETTER_FRESH_S = 86400
# Ids named in one hold reason; the rest are counted.
LETTER_NAMES = 5
```

Definition 3 (new function):

```python
def pending_letters(project: Path, tool: str, now: float | None = None) -> list[str]:
    """U210: ids of fresh ACTIONABLE letters addressed to `tool` that are still in the inbox (not yet acked)."""
    from v7_harness.coord import desk_delta

    inbox = next_card.coord_root(Path(project)) / ".coord" / "mailbox" / "inbox"
    moment = time.time() if now is None else now
    found = []
    for path in sorted(inbox.glob("*.json")) if inbox.is_dir() else []:
        if path.name.startswith("evt_") or desk_delta.own_letter(path, tool):
            continue
        body = desk_delta._payload(path)
        target = desk_delta.canonical(str(body.get("requested_target") or body.get("to") or ""))
        try:
            fresh = moment - path.stat().st_mtime <= LETTER_FRESH_S
        except OSError:
            fresh = False
        if target == tool and body.get("wake_class") == "ACTIONABLE" and fresh:
            found.append(path.stem)
    return found
```

Definition 4 (new function):

```python
def letter_hold(project: Path, tool: str, now: float | None = None) -> dict[str, Any] | None:
    """U210: an unread letter is owed work even when the schedule names no card (relay_9f21437a receipt); each letter
    holds once, so a letter left unacked never spins the gate."""
    letters = pending_letters(project, tool, now=now)
    guard = Path(project) / ".coord" / "presence" / f"stop_gate_{tool}_letters.json"
    try:
        held = json.loads(guard.read_text(encoding="utf-8")).get("held", [])
    except (OSError, ValueError, AttributeError):
        held = []
    new = [name for name in letters if name not in held]
    if not new:
        return None
    _write_atomic(guard, {"held": letters})
    more = f" (+{len(new) - LETTER_NAMES} more)" if len(new) > LETTER_NAMES else ""
    return {"decision": HOLD_DECISION.get(tool, "block"),
            "reason": f"Unread letter(s) for {tool}: {', '.join(new[:LETTER_NAMES])}{more}. Open each, act on it, "
                      "deliver the result, then `coord ack --id <full id>`"}
```

Definition 5 (the existing `gate`, complete; only the three lines after the R7 check are new):

```python
def gate(project: Path, tool: str, session: str | None = None, now: float | None = None) -> dict[str, Any] | None:
    project = Path(project)
    if not session:
        return None  # U146a-R: no session id, no claim and no block (UNKNOWN is no ground for acting)
    from v7_harness.coord import presence

    if presence.read(project, tool, now=now).get("state") in NO_BUDGET_STATES:
        return None  # R7: no claim and no paid re-entry for a tool without budget
    hold = letter_hold(project, tool, now=now)
    if hold is not None:
        return hold
    step = next_card.next_step(project, tool, claim=True, session=session, now=now)
    if step.get("state") != "NEXT":
        return None
    card = step["card"]
    guard_path = project / ".coord" / "presence" / f"stop_gate_{tool}.json"
    try:
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
        if not isinstance(guard, dict):
            guard = {}
    except (OSError, ValueError):
        guard = {}
    progress = progress_signature(project)
    blocks = guard.get("blocks") if isinstance(guard.get("blocks"), int) else 0
    if guard.get("card") != card or guard.get("progress") != progress:
        blocks = 0
    if blocks >= MAX_BLOCKS:
        log = project / ".coord" / "log" / "stop_gate.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        row = {"kind": "BLOCKED", "tool": tool, "card": card, "blocks": blocks,
               "at": time.time() if now is None else now}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return None
    _write_atomic(guard_path, {"card": card, "blocks": blocks + 1, "progress": progress})
    return {"decision": HOLD_DECISION.get(tool, "block"),
            "reason": f"NEXT {card} (owner {step.get('owner')}) is ready: start it now; human-list items go in the "
                      "final batched report"}
```

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
