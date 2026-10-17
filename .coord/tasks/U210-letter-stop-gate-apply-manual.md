```contract
work_id: U210-L3
worker: apply
apply_after: U210-L2
goal: deterministic apply of the U210 letter hold in the Stop gate (constants, pending_letters, letter_hold, three lines in gate)
inputs:
- v7_harness/coord/stop_gate.py sha256=4040462281cc32310f144b3e738ae14a30ad27146544c8d0f87d676f5bc0ba8f
- tests/test_u210_letter_stop_gate.py sha256=8a3356c04ee7adc9c7c1c297ebc3cedfbccb595632f19783b12f89b3f8263cb7
allow:
- v7_harness/coord/stop_gate.py
acceptance: python -m unittest tests.test_u210_letter_stop_gate tests.test_u146a_next_card tests.test_u146b_auto_gates tests.test_u146a_r_ownership tests.test_u146a_r2_claim_lock
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Work ID U210-L3. Prior receipts kept: U210-L1 local SPLICE_UNSUPPORTED:Try (fragment emitted at top level); U210-L2
local acceptance_exit 1 (the 7B model dropped the three dictated gate() lines and every comment/docstring). Two local
failures on this card, so the exact candidate below is applied deterministically.

===EDIT: v7_harness/coord/stop_gate.py===
<<<<<<< SEARCH
NO_BUDGET_STATES = ("LIMITED",)
=======
NO_BUDGET_STATES = ("LIMITED",)
# U210: a letter counts as processed only once `coord ack` moves it out of the inbox. The inbox backlog that predates
# this rule (1885 items on 2026-10-18) is not news, so only letters younger than one day hold a stop.
LETTER_FRESH_S = 86400
# Ids named in one hold reason; the rest are counted.
LETTER_NAMES = 5
>>>>>>> REPLACE

===EDIT: v7_harness/coord/stop_gate.py===
<<<<<<< SEARCH
def _write_atomic(path: Path, data: dict) -> None:
=======
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


def _write_atomic(path: Path, data: dict) -> None:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/stop_gate.py===
<<<<<<< SEARCH
        return None  # R7: no claim and no paid re-entry for a tool without budget
    step = next_card.next_step(project, tool, claim=True, session=session, now=now)
=======
        return None  # R7: no claim and no paid re-entry for a tool without budget
    hold = letter_hold(project, tool, now=now)
    if hold is not None:
        return hold
    step = next_card.next_step(project, tool, claim=True, session=session, now=now)
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
