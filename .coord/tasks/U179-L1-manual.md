```contract
work_id: U179-L1
worker: local
goal: U179 slice A - the structured watcher runs the long-wait scan on a timer and wakes once per stalled wait
inputs:
- v7_harness/coord/watch.py sha256=8033461d3a1842b8f33f662af96f3ff8506ee30a8cdb07aa2f5085264a7f1f82
- v7_harness/coord/stall.py sha256=f33fef51fede7c9694931f1a8484cf65fae24f773b2bab70c4f9709b8d85dda0
allow:
- v7_harness/coord/watch.py
- v7_harness/coord/stall.py
context_allow:
- v7_harness/coord/watch.py
- v7_harness/coord/stall.py
acceptance: python -m unittest tests.test_u179_wait_watchdog tests.test_u166_merge_route_no_wait tests.test_u141a_wake_policy tests.test_u141a_rev6_thrift_wake tests.test_u117_watch_wakes_session tests.test_u94r1_watch_scan_cost
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card U179 slice A. Two small edits. Change nothing else.

1. In `v7_harness/coord/stall.py`, function `scan`: the dict `entry` built for each due wait gets two more keys,
   `"author": wait["author"]` and `"since": wait["since"]`.
2. In `v7_harness/coord/watch.py`:
   - add the module constant `STALL_SCAN_S = 60.0` after `PENDING_MAX_AGE_S`;
   - add a function `_stalled_wait(project, tools, clock)` before `watch`. It imports `stall` from
     `v7_harness.coord` inside the function and, for each tool in `tools`, calls
     `stall.scan(project, tool, now=clock())`; an `OSError` or `ValueError` skips that tool. For each entry of
     `result["stalled"] + result["blocked"]`: skip it unless the tool is the entry's `author`, its `waiting_on` or its
     `owner` (use `entry.get("owner")`); build `key = f"stall:{entry['item']}:{entry['since']}"`; when
     `claim_wake(project, tool, key, hashlib.sha256(key.encode("utf-8")).hexdigest(), clock=clock)` returns
     `"CLAIMED"`, return `{"id": key, "reason": "STALLED_WAIT", "item": entry["item"], "kind": entry["kind"],
     "waiting_on": entry["waiting_on"], "age_s": entry["age_s"], "owner": entry.get("owner"),
     "requested_target": tool}`. Return None when nothing was claimed;
   - in `watch`, set `next_stall_scan = clock()` before the `while True:` loop; inside the loop, after the
     `for message_id in box.list_inbox():` loop and before `if clock() >= deadline:`, when `structured` and
     `clock() >= next_stall_scan`, set `next_stall_scan = clock() + STALL_SCAN_S`, call `_stalled_wait` and return its
     result when it is not None.

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
