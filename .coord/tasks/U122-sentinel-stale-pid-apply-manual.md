```contract
work_id: U122
worker: apply
goal: sentinel loop ignores a pid file whose pid Windows reused for an unrelated process (U122)
inputs:
- v7_harness/cli.py sha256=ca5f0a75f12af546794ad4983edf3da7f21b118ed91158ddd262bec88368b582
allow:
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u122_sentinel_stale_pid tests.test_u37_install_everywhere tests.test_u91_stale_sentinel_task
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the two blocks below exactly.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
def cmd_coord_sentinel(args: argparse.Namespace) -> int:
=======
def _sentinel_loop_owner(pid_file: Path, interval: float) -> int:
    """Pid of a live sentinel loop holding pid_file, else 0. U122: Windows reuses pids, so only a file the loop
    rewrote within three cycles (floor 180 s; one tick took up to 8 s) counts; an older one is stale."""
    from .coord.sentinel import _is_pid_alive
    import time
    try:
        running = int(pid_file.read_text(encoding="utf-8").strip())
        age = time.time() - pid_file.stat().st_mtime
    except (OSError, ValueError):
        return 0
    return running if age < max(180.0, 3 * interval) and running != os.getpid() and _is_pid_alive(running) else 0


def cmd_coord_sentinel(args: argparse.Namespace) -> int:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
        from .coord.sentinel import _is_pid_alive

        pid_file = project / ".work" / "sentinel" / "loop.pid"
        try:
            running = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            running = 0
        if running and running != os.getpid() and _is_pid_alive(running):
            _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        while True:
=======
        pid_file = project / ".work" / "sentinel" / "loop.pid"
        running = _sentinel_loop_owner(pid_file, args.interval)
        if running:
            _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            pid_file.write_text(str(os.getpid()), encoding="utf-8")  # U122: each cycle refreshes the heartbeat
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
