```contract
work_id: U113-P1B
worker: local
goal: presence.desk_label names an expired heartbeat IDLE(age) and a never-seen tool UNKNOWN
inputs:
- v7_harness/coord/presence.py sha256=52516b499dd09303f36708429b16c0434c679b3398800d1aa7dcf9169364951e
- tests/test_u113_desk_truth.py sha256=563ea9a21ea43ba28200af050225b98de723f4bfcda7020602d6c8a325efc61c
allow:
- v7_harness/coord/presence.py
acceptance: python -m unittest tests.test_u113_desk_truth.DeskNamesIdleTools.test_desk_label_words tests.test_u113_desk_truth.DeskNamesIdleTools.test_idle_still_does_not_conduct tests.test_u61_watcher_routes
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/coord/presence.py with one exact SEARCH/REPLACE block. Add a new function directly above the
line that starts with "# U57-A (2026-09-27)". Leave two blank lines before and after it. The function:

def desk_label(info: dict[str, Any], now: float | None = None) -> str:
    """The desk word for one tool (U113): an expired heartbeat reads IDLE(<age>), a tool never seen UNKNOWN."""

Behaviour:
- If info.get("state") is not "UNKNOWN", return that state string unchanged.
- Otherwise compute seen = _epoch(info.get("observed_at")). If seen is None, return "UNKNOWN".
- Otherwise age = (time.time() if now is None else now) - seen, in seconds. If age is under 3600, return
  f"IDLE({int(age // 60)}m)", else return f"IDLE({int(age // 3600)}h)".
Put a one-line comment above the def starting with "# U113:" saying the desk said antigravity=UNKNOWN while Antigravity
was open and had answered three hours before; routing still treats IDLE like UNKNOWN (fail closed).
Change nothing else. `_epoch`, `time` and `Any` already exist in this file.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
