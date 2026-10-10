```contract
work_id: U179-A2
worker: apply
apply_after: U179-L1
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

Card U179 slice A. The Ollama run U179-L1 rewrote both files and failed acceptance (40 of 66 tests); U179-A1 read the clock once more than a frozen U117 test allows. Dictation: copy the
edit blocks below exactly. Change nothing else.

Design (proposal .work/cards/U179_claude_proposal.md, alternative B): `stall.scan` had one automatic caller, the
per-prompt hook, so an idle session never ran the long-wait procedure. The watcher that every tool already keeps running
calls it on a timer and ends the watch with STALLED_WAIT. The existing O_EXCL wake receipt (`claim_wake`) gives one wake
per wait instance (item + since) and tool. Only a tool with a part in the wait (author, waited-on, takeover owner) is
woken, so one stalled wait does not cost three paid turns. Not in this slice: wait records for delivered letters, and
recovery of a claim whose process died before printing (proposal 7.1, 7.3).

===EDIT: v7_harness/coord/stall.py===
<<<<<<< SEARCH
            entry = {"item": wait["item"], "kind": wait["kind"], "waiting_on": wait["waiting_on"],
                     "age_s": int(age), "route": owners}
=======
            entry = {"item": wait["item"], "kind": wait["kind"], "waiting_on": wait["waiting_on"],
                     "age_s": int(age), "route": owners, "author": wait["author"], "since": wait["since"]}
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
PENDING_MAX_AGE_S = 300.0
=======
PENDING_MAX_AGE_S = 300.0
# U179: 60 s between long-wait scans. A scan takes the stall lock, reads the schedule and the queued letters and
# writes three small state files, so it does not run on every 2 s inbox scan; 60 s bounds lateness to 3% of
# stall.MAX_WAIT_S (1800 s). Never tokens.
STALL_SCAN_S = 60.0
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
def watch(project: Path, tools: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
=======
def _stalled_wait(project: Path, tools: tuple[str, ...], clock: Callable[[], float]) -> dict[str, Any] | None:
    """U179: the first stalled wait one of `tools` has a part in and has not been woken for yet."""
    from v7_harness.coord import stall

    for tool in tools:
        try:
            result = stall.scan(project, tool, now=clock())
        except (OSError, ValueError):
            continue  # a locked or unreadable stall state: the next scan looks again, the watch goes on
        for entry in result["stalled"] + result["blocked"]:
            if tool not in (entry["author"], entry["waiting_on"], entry.get("owner")):
                continue
            # One receipt per wait instance: a step that waits again later has a new `since` and wakes again.
            key = f"stall:{entry['item']}:{entry['since']}"
            if claim_wake(project, tool, key, hashlib.sha256(key.encode("utf-8")).hexdigest(),
                          clock=clock) == "CLAIMED":
                return {"id": key, "reason": "STALLED_WAIT", "item": entry["item"], "kind": entry["kind"],
                        "waiting_on": entry["waiting_on"], "age_s": entry["age_s"], "owner": entry.get("owner"),
                        "requested_target": tool}
    return None


def watch(project: Path, tools: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
    deadline = clock() + timeout_s
    try:
        while True:
=======
    deadline = clock() + timeout_s
    next_stall_scan = deadline - timeout_s  # the first scan runs at once; no extra clock read (U117 test counts them)
    try:
        while True:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                        return {**found, "wake_class": cls}
            if clock() >= deadline:
=======
                        return {**found, "wake_class": cls}
            if structured and clock() >= next_stall_scan:
                next_stall_scan = clock() + STALL_SCAN_S
                stalled = _stalled_wait(Path(project), tools, clock)
                if stalled is not None:
                    return stalled
            if clock() >= deadline:
>>>>>>> REPLACE

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
