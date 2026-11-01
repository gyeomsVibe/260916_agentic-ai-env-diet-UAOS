```contract
work_id: U277-A3
worker: apply
goal: Fix the U117 regression from U277-A2 (test_the_cli_flag_reaches_the_heartbeat KeyError beat) by reading the clock once per watch scan for both the beat and the U277 request scan
inputs:
- v7_harness/coord/watch.py sha256=4165a8e0c56d46f1dff77931e9f5123cad59e79ba383bd305640b0c5ee980672
allow:
- v7_harness/coord/watch.py
acceptance: python -m unittest tests.test_u117_watch_wakes_session tests.test_u277_request_wake tests.test_message_id_collision tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u118_agy_letter_unread && python "D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.claude/worktrees/unapproved-nonstop-orchestration-903a95/.work/u277/judge_v2_test.py"
forbidden: edits outside allow; editing tests; design changes; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT blocks exactly. Five lines change and one line is added in watch.py. The fake clock in the U117 test allows a fixed number of clock reads per scan, and A2 added two more reads.

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
def _request_wake(project: Path, tools: tuple[str, ...], session: str | None, clock: Callable[[], float],
=======
def _request_wake(project: Path, tools: tuple[str, ...], session: str | None, now: float,
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
        transitions = requests.scan(project, now=clock())
=======
        transitions = requests.scan(project, now=now)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
            if requests.claim_wake(project, request_id, session=session or "", now=clock(), started_at=started_at):
=======
            if requests.claim_wake(project, request_id, session=session or "", now=now, started_at=started_at):
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
            _beat(project, tools, token, interval_s, clock(), wakes_session,
=======
            now = clock()  # one read serves the beat and the request scan (U117 test counts clock reads)
            _beat(project, tools, token, interval_s, now, wakes_session,
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                woken = _request_wake(Path(project), tools, requester_session, clock, started_at)
=======
                woken = _request_wake(Path(project), tools, requester_session, now, started_at)
>>>>>>> REPLACE
===END===
