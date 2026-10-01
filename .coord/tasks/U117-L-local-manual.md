```contract
work_id: U117-L
worker: local
goal: A watcher that wakes its own session takes real deltas for Claude; plain watchers keep U64
inputs:
- tests/test_u117_watch_wakes_session.py sha256=825b610c719a9029c62e790791aff275982897a9e6d81fc80b42568219b590c4
- v7_harness/coord/watch.py sha256=5747477dc79325c044133fcdd7d10a3acb5dd6c3c95099ffed3eb63a8ccec20b
- v7_harness/coord/deliver.py sha256=7c5dcd609aaf9a18f6a37c8f958f2fb3c420339fef1ff3dc0c8b5e2431311c21
allow:
- v7_harness/coord/watch.py
- v7_harness/coord/deliver.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u117_watch_wakes_session tests.test_u57_desk_signals tests.test_u61_watcher_routes tests.test_u71_three_tool_e2e
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Output these SEARCH/REPLACE edits unchanged, one per ===EDIT=== section; change nothing else.

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
def _beat(project: Path, tools: tuple[str, ...], token: str, interval_s: float, moment: float) -> None:
=======
def _beat(project: Path, tools: tuple[str, ...], token: str, interval_s: float, moment: float,
          wakes_session: bool = False) -> None:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                                   "expires_at": moment + live_for}), encoding="utf-8")
=======
                                   "expires_at": moment + live_for, "wakes_session": wakes_session}),
                       encoding="utf-8")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
def _addressed(payload: Any, tools: tuple[str, ...]) -> bool:
=======
def watcher_wakes(project: Path, tool: str) -> bool:
    """U117: a live watcher whose exit wakes its own session (a Claude Code background task) takes real deltas too."""
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return watcher_live(project, tool) and isinstance(record, dict) and record.get("wakes_session") is True


def _addressed(payload: Any, tools: tuple[str, ...]) -> bool:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
          sleep: Callable[[float], None] | None = None) -> dict[str, Any] | None:
=======
          sleep: Callable[[float], None] | None = None, wakes_session: bool = False) -> dict[str, Any] | None:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
            _beat(project, tools, token, interval_s, clock())
=======
            _beat(project, tools, token, interval_s, clock(), wakes_session)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox scans (default: 30)")
=======
    p_coord_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox scans (default: 30)")
    p_coord_watch.add_argument("--wakes-session", action="store_true",
                               help="U117: this watch runs as a background task whose exit wakes its session")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval)
=======
    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval,
                  wakes_session=args.wakes_session)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        from v7_harness.coord.watch import watcher_live
        if watcher_live(desk, "claude") and not _requires_wake(message):
=======
        from v7_harness.coord.watch import watcher_live, watcher_wakes
        # U117: a watcher that wakes its own session takes real deltas too; U64's headless turn stays for the rest.
        if watcher_live(desk, "claude") and (not _requires_wake(message) or watcher_wakes(desk, "claude")):
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
