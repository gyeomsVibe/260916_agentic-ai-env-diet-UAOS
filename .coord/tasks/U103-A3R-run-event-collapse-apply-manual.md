```contract
work_id: U103-A3R
worker: apply
goal: Collapse pilot run events into one counted line per tool so commits, notes and relays stay inside the desk delta's 12-line cap (rerun of U103-A3, blocked by its acceptance).
inputs:
- tests/test_u103_desk_delta.py sha256=63b615b472f698fbdc7968194d56c9f9c266237ac5d661f6ba297f29790a4a56
allow:
- v7_harness/coord/desk_delta.py
context_allow:
- tests/test_u103_desk_delta.py
acceptance: python -m unittest tests.test_u103_desk_delta
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 13 lines, after the U103-L1 Ollama run). First real run on this project (2026-10-01): 26 of Codex's 27 delta items were Claude's pilot run events (`evt_*`), so the 12-line cap hid the commits and notes. Run events now collapse into one counted line per tool with the newest shown (U103-A3 collapsed all tools into one line and hid one tool's event; its acceptance failed and the gate blocked it), and relays and git changes come first.

===EDIT: v7_harness/coord/desk_delta.py===
<<<<<<< SEARCH
    items: list[str] = []
    # Letters
    inbox = project / ".coord" / "mailbox" / "inbox"
    if inbox.is_dir():
        for letter in sorted(inbox.glob("*.json")):
            if not letter.is_file() or letter.stat().st_mtime <= since or own_letter(letter, tool):
                continue
            items.append(f"letter {letter.stem}: {summary_of(letter)}")
    # PLAN
    rows = plan_rows(project / ".coord" / "PLAN.md")
    for key, status in rows.items():
        if key in seen and seen[key] != status:
            items.append(f"PLAN {key}: {seen[key]} -> {status}")
    items.extend(absence_items(project, since, tool))
=======
    items: list[str] = []
    rows = plan_rows(project / ".coord" / "PLAN.md")
    for key, status in rows.items():
        if key in seen and seen[key] != status:
            items.append(f"PLAN {key}: {seen[key]} -> {status}")
    # Pilot run events (`evt_*`) collapse to one counted line per tool, newest shown; relays and git changes come first.
    events: dict[str, list[Path]] = {}
    inbox = project / ".coord" / "mailbox" / "inbox"
    if inbox.is_dir():
        for letter in sorted(inbox.glob("*.json")):
            if not letter.is_file() or letter.stat().st_mtime <= since or own_letter(letter, tool):
                continue
            if letter.name.startswith("evt_"):
                events.setdefault(canonical(_payload(letter).get("actor", "")) or "unknown", []).append(letter)
            else:
                items.append(f"letter {letter.stem}: {summary_of(letter)}")
    items.extend(absence_items(project, since, tool))
    for actor, group in events.items():
        items.append(f"{len(group)} run event(s) from {actor}, newest {group[-1].stem}: {summary_of(group[-1])}")
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
