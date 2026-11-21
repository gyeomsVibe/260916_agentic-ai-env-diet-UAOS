# WATCH-REPLAY (revision 4; target 0.6.5 after U333 0.6.4; not committed yet)

- Defect: `coord watch --wakes-session` re-armed exited at once with REQUEST_ANSWERED for an already handled request.
- Cause: a WAKE_PENDING claim whose waker exited was reclaimable by any later-started watcher; nothing ever acked the request.
- Rev3 fault (Codex REVISE relay_ca8816ec): `surfaced_at` was treated as consumer receipt, but it only proves the producer flushed; a real child writing into an unread pipe (child exit 0, parent bytes 0) set it and the request was never recovered.
- Rev4 fix: `surfaced_at` is a producer receipt that holds replay only for the claim window (`waker.lease_until`, WAKE_LEASE_S = 1800 s). After it, `requests.replay_due` lets one later watcher re-claim as a new `wake_generation` (CAS, sibling at the same moment refused); `mark_surfaced` is fenced to claimant pid + generation; at most WAKE_MAX_GENERATIONS = 3 wakes (1 + 2 recoveries) for a never-acking consumer. Only the requester's `coord ack` (or cancel) settles the request. `watch._request_wake` skips rows inside the window without a registry write.
- Tests: tests/test_watch_replay.py 7 passed (exit 0; includes real unread-pipe subprocess regression and per-generation bound); related u117/u141a/u225/u277/u291/u296/u310 70 passed (exit 0). Logs: .work/watch_replay_r4_a.log, .work/watch_replay_r4_b.log.
- Residual: VERSION still staged at 0.6.3; must be re-bumped to 0.6.5 after U333 (0.6.4) merges, before commit.
- Next: Antigravity diff review of rev4 (author != judge), then version bump, commit, PR.
