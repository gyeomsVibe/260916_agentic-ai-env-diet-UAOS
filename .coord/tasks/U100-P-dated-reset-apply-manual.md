```contract
work_id: U100-P
worker: apply
goal: Read the date in Codex weekly reset messages in v7_harness/coord/presence.py so a dated limit is not treated as one hour.
inputs:
- v7_harness/coord/presence.py sha256=f8c5ada4b6871728b81bd12b91865ba35fa1d0301fad79a16199f8c71749e48a
- tests/test_u100p_codex_dated_reset.py sha256=c593d0a9255ff96197b66ac13e063fcc8cc64fa38ee1ed203574928ee67ec86d
allow:
- v7_harness/coord/presence.py
acceptance: python -m unittest tests.test_u100p_codex_dated_reset tests.test_u57_desk_signals
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly. Codex's weekly limit prints a date ("try again at Oct 4th, 2026 2:35 AM"); the clock-only pattern missed it and fell back to one hour, so a 4-day limit looked like 1 hour.

===EDIT: v7_harness/coord/presence.py===
<<<<<<< SEARCH
def _reset_at(message: str, completed_at: float) -> float:
=======
def _reset_at(message: str, completed_at: float) -> float:
    # U100-P: a weekly limit prints the date too; read it before the clock-only form (2026-09-28 rollout).
    dated = re.search(r"try again at ([A-Z][a-z]{2}) (\d{1,2})(?:st|nd|rd|th), (\d{4}) (\d{1,2}):(\d{2})\s*([AP]M)",
                      message or "", re.IGNORECASE)
    if dated:
        try:
            day = datetime.strptime(f"{dated.group(1).title()} {dated.group(2)} {dated.group(3)}", "%b %d %Y")
        except ValueError:
            return completed_at + UNPARSED_RESET_S
        hour = int(dated.group(4)) % 12 + (12 if dated.group(6).upper() == "PM" else 0)
        return day.replace(hour=hour, minute=int(dated.group(5))).timestamp()
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
