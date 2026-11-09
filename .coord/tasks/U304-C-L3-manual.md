```contract
work_id: U304-C-L3
worker: local
goal: Implement paced_allowance (budget pacing of flagship grants) in schedule_planner.py
inputs:
- v7_harness/coord/schedule_planner.py sha256=5f2bbb03458f8abdbb7e082500a4207043642c5a02c464bdbc8bc4deedb7aac2
allow:
- v7_harness/coord/schedule_planner.py
acceptance: python -m pytest tests/test_u304c_schedule_planner.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Replace the one line `raise NotImplementedError("U304-C-L3: paced_allowance")` in v7_harness/coord/schedule_planner.py with the body below. Change nothing else. Use one ===EDIT block; the SEARCH is exactly that raise line (4-space indent).

`paced_allowance(budget, *, now=None)`: `budget` is the output of `validate_budget`, {tool: entry}; each entry has int `remaining_5h_tokens`, `remaining_week_tokens`, float epoch `_reset_5h`, `_reset_week`, and `plan`, `measured_at`.
- `now = time.time() if now is None else now`
- `window_s = float(THRESHOLDS["budget_window_h"]["value"]) * 3600`
- `out: dict[str, dict[str, Any]] = {}`; for each `tool, entry` in `budget.items()`:
  - `windows_left = max(1.0, (entry["_reset_week"] - now) / window_s)`
  - `weekly_paced = max(0, int(entry["remaining_week_tokens"])) / windows_left`
  - comment line: `# A passed 5h reset means the window refilled after the measurement; only the weekly pace binds then.`
  - `five_h = None if entry["_reset_5h"] <= now else max(0, int(entry["remaining_5h_tokens"]))`
  - `paced = int(weekly_paced if five_h is None else min(five_h, weekly_paced))`
  - `share = float(THRESHOLDS["flagship_pace_share"][tool])`
  - `out[tool] = {"paced_tokens": paced, "share": share, "flagship_tokens_left": int(paced * share), "plan": entry["plan"], "measured_at": entry["measured_at"]}`
- `return out`
