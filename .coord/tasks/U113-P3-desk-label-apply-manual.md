```contract
work_id: U113-P3
worker: apply
goal: The desk names an expired heartbeat IDLE(age) in every hook line; routing unchanged
inputs:
- v7_harness/coord/presence.py sha256=52516b499dd09303f36708429b16c0434c679b3398800d1aa7dcf9169364951e
- v7_harness/coord/hook_context.py sha256=cbcca78b26a76687e4dd22f1d282c5ccb4c9f3a220592230dcccb31d0efd4528
- tests/test_u113_desk_truth.py sha256=563ea9a21ea43ba28200af050225b98de723f4bfcda7020602d6c8a325efc61c
allow:
- v7_harness/coord/presence.py
- v7_harness/coord/hook_context.py
acceptance: python -m unittest tests.test_u113_desk_truth tests.test_u61_watcher_routes
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. (Ollama run U113-P1B compared strings with `is not`, skipped the comment, and put the
function at the end of the file: judge verdict REWORK.)

===EDIT: v7_harness/coord/presence.py===
<<<<<<< SEARCH
# U57-A (2026-09-27): Codex's UserPromptSubmit hook writes ACTIVE before the turn runs, so a relay prompt that Codex
=======
# U113: the desk said antigravity=UNKNOWN while Antigravity was open and had answered three hours before. Routing still
# treats IDLE like UNKNOWN (fail closed); only the word on the desk changes.
def desk_label(info: dict[str, Any], now: float | None = None) -> str:
    """The desk word for one tool: an expired heartbeat reads IDLE(<age>), a tool never seen UNKNOWN."""
    state = str(info.get("state") or "UNKNOWN")
    seen = _epoch(info.get("observed_at")) if state == "UNKNOWN" else None
    if seen is None:
        return state
    age = (time.time() if now is None else now) - seen
    return f"IDLE({int(age // 60)}m)" if age < 3600 else f"IDLE({int(age // 3600)}h)"


# U57-A (2026-09-27): Codex's UserPromptSubmit hook writes ACTIVE before the turn runs, so a relay prompt that Codex
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
from typing import Any, Iterable
=======
from typing import Any, Iterable

from v7_harness.coord.presence import desk_label
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    reviews = sum(1 for item in inbox if item.startswith("rsi_review_"))
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
=======
    reviews = sum(1 for item in inbox if item.startswith("rsi_review_"))
    desk = ", ".join(f"{tool}={desk_label(info)}" for tool, info in presence.items())
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
=======
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={desk_label(info)}" for tool, info in presence.items())
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
