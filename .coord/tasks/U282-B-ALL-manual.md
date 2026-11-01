```contract
work_id: U282-B-ALL
worker: apply
apply_after: U282-S1-DELIVER
goal: No paid Codex turn for self-addressed or no-wake letters (R1 sender skip, R2 QUEUED_NOTICE)
inputs:
- tests/test_u282_codex_relay_filter.py sha256=cf1e65f4e75f92d7ec7a22f72449522bc9c8c25bca2e156528628446c8f323e4
allow:
- v7_harness/coord/deliver.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u282_codex_relay_filter tests.test_u113_desk_truth tests.test_u74_closure tests.test_u134_dispatch_on_active tests.test_u115_card_window_route
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 180
remote_budget_tokens: 0
```

## Instructions for the worker

Work ID `U282-B-ALL`. Author Claude (design), worker Ollama (exact dictation), judge Codex.
Goal: a letter that asks Codex for nothing never becomes a paid `codex queue` turn. R1: auto routing never resolves
to the sender. R2: a NOTICE / verdict_requested=False / bare ACK_ONLY letter to Codex stays in the inbox
(QUEUED_NOTICE). Fixed acceptance: tests/test_u282_codex_relay_filter.py (already in the tree, do not edit).
Apply exactly these blocks; change nothing else.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    ok = result.reason in ("PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY",
                           "QUEUED_UNTIL_ACTIVE")
=======
    # U282: QUEUED_NOTICE is a letter to Codex that asks for no turn, left in the inbox; also not a failure.
    ok = result.reason in ("PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY",
                           "QUEUED_UNTIL_ACTIVE", "QUEUED_NOTICE")
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    return _requires_wake(message)


# ── 비밀 검사
=======
    return _requires_wake(message)


def _declines_turn(message: str, fields: dict[str, Any]) -> bool:
    """U282: the letter itself says it needs no turn. An untagged letter without a marker is not a decline."""
    if fields.get("wake_class") == "ACTIONABLE" or fields.get("verdict") or fields.get("verdict_requested") is True:
        return False
    # wake_class ACK_ONLY never gets here (classify refuses it as INVALID_INTENT); the marker is the text token.
    if fields.get("wake_class") == "NOTICE" or fields.get("verdict_requested") is False:
        return True
    # A marker declines only when no wake token stands beside it: losing a real request costs more than one turn
    # (Codex judge REVISE: "ACTIONABLE_DELTA verdict_requested=yes ...; previous status ACK_ONLY" was silenced).
    upper = _QUOTED_RE.sub(" ", _FENCE_RE.sub(" ", message)).upper()
    stripped = _NEGATED_RE.sub(" ", upper)
    return bool(_ACK_RE.search(upper)) and not any(pattern.search(stripped) for pattern in _WAKE_RES)


# ── 비밀 검사
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        if read_presence(desk, "codex")["state"] == "ACTIVE":
            target = "codex"
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
=======
        # U282 R1: auto routing never picks the sender; Codex mailed itself twice (relay_6a3014c5, relay_f0722b8d).
        sender = actor.lower()
        if sender != "codex" and read_presence(desk, "codex")["state"] == "ACTIVE":
            target = "codex"
        elif sender != "claude" and (read_presence(desk, "claude")["state"] == "ACTIVE"
                                     or watcher_live(desk, "claude")):
            target = "claude"
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    if target is None and queued_for:
        return _queue_until_active(project, queued_for, message_id=message_id, digest=digest, actor=actor,
=======
    if "codex" in (target, queued_for) and _declines_turn(message, explicit):
        # U282 R2: every `codex queue` item is a paid Codex turn (~140k context); a letter that asks for nothing stays
        # in the inbox, which Codex's hooks show as desk delta (U103), and is never queued for a later ACTIVE turn.
        return DeliverResult(False, "codex", "QUEUED_NOTICE", (), "", message_id, digest,
                             str(box.inbox_dir / f"{message_id}.json"))
    if target is None and queued_for:
        return _queue_until_active(project, queued_for, message_id=message_id, digest=digest, actor=actor,
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
