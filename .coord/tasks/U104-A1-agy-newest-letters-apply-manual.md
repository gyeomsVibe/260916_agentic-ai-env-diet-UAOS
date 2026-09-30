```contract
work_id: U104-A1
worker: apply
goal: Antigravity's prompt hook shows the newest letters addressed to it and quotes the newest one (U104).
inputs:
- tests/test_u104_agy_sees_new_letters.py sha256=bcd80058c3b63f6cc2a4ee2413a997a8ae54c983ddb00b665d83da8972af4d88
allow:
- v7_harness/coord/hook_context.py
context_allow:
- tests/test_u104_agy_sees_new_letters.py
acceptance: python -m unittest tests.test_u104_agy_sees_new_letters tests.test_u95a_antigravity_briefing
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly (judge-dictated, 17 lines). Antigravity's prompt hook listed the five oldest letters addressed to it by file name, so a new work order (11th of 12) never showed and the user relayed it by hand (U104). Letters now come newest first and the line quotes the newest letter's text.

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    """Ids of inbox letters addressed to Antigravity (requested_target or to), in name order."""
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    found: list[str] = []
    if not box_dir.is_dir():
        return found
    for path in sorted(box_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
=======
    """Ids of inbox letters addressed to Antigravity (requested_target or to), newest first (U104)."""
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    found: list[tuple[float, str]] = []
    if not box_dir.is_dir():
        return []
    for path in box_dir.glob("*.json"):
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text(encoding="utf-8"))
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
            found.append(path.stem)
    return found
=======
            found.append((mtime, path.stem))
    # U104: name order showed the five oldest (2026-09-26) and hid a new verdict order; newest first instead.
    return [stem for _, stem in sorted(found, reverse=True)]
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
        line += (f"{len(letters)} letter(s) for antigravity in .coord/mailbox/inbox: {', '.join(letters[:AGY_SHOWN])}. "
=======
        try:
            newest = json.loads((Path(project) / ".coord" / "mailbox" / "inbox" / f"{letters[0]}.json")
                                .read_text(encoding="utf-8"))["payload"].get("message", "")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            newest = ""  # claimed or mid-write: the ids still name it
        line += (f"{len(letters)} letter(s) for antigravity in .coord/mailbox/inbox, newest first: "
                 f"{', '.join(letters[:AGY_SHOWN])}. Newest says: {str(newest)[:160]} "
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    return line[:900]
=======
    return line[:1100]  # U104: +160 chars for the newest letter's text, so the report instruction is not cut
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
