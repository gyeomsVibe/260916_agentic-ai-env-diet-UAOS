```contract
work_id: U304-A-L3
worker: local
goal: In v7_harness/coord/sentinel.py, re-spawn a dead recorded Flagman daemon in the sentinel cycle.
inputs:
- v7_harness/coord/sentinel.py sha256=168c2510710518b1a2399a4e4b4b63c9b4bfbb83e3962096b94f8c0c69230280
allow:
- v7_harness/coord/sentinel.py
acceptance: python -c "import v7_harness.coord.sentinel"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly, in order.

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        flagman_3tool = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    bell = ring_bell(project_root, box, runner=runner, sessions_dir=sessions_dir) if ring else {"rung": False, "reason": "RING_OFF"}

=======
        flagman_3tool = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    # U304-A: this hook pulse exits in seconds, so it also re-spawns a dead resident daemon. Only a project that
    # recorded a daemon once (`.coord/flagman_daemon.json`) gets one, so a scratch root never grows a process.
    try:
        from ..disjoint_mediator import (
            FLAGMAN_DAEMON_INTERVAL_S,
            ensure_independent_flagman_daemon,
            flagman_daemon_meta_file,
        )

        flagman_daemon: Any = (
            ensure_independent_flagman_daemon(project_root, interval_s=FLAGMAN_DAEMON_INTERVAL_S)["daemon_status"]
            if flagman_daemon_meta_file(project_root).is_file()
            else "NOT_INSTALLED"
        )
    except Exception as exc:  # noqa: BLE001 - a failed spawn must not stop the operator
        flagman_daemon = f"{type(exc).__name__}: {exc}"[:200]

    bell = ring_bell(project_root, box, runner=runner, sessions_dir=sessions_dir) if ring else {"rung": False, "reason": "RING_OFF"}

>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        "owner_wake": owner_res,
        "flagman_3tool": flagman_3tool,
    }
=======
        "owner_wake": owner_res,
        "flagman_3tool": flagman_3tool,
        "flagman_daemon": flagman_daemon,
    }
>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
