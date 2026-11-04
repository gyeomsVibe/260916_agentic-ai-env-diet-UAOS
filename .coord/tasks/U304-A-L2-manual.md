```contract
work_id: U304-A-L2
worker: local
goal: In v7_harness/coord/hud_live.py, re-ensure the Flagman daemon before the first render and every refresh cycle.
inputs:
- v7_harness/coord/hud_live.py sha256=2ff34961273eede686e4d54051eeab73d16647c62c10f4599062577bf787f20c
allow:
- v7_harness/coord/hud_live.py
acceptance: python -m pytest tests/test_u303_hud_render.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly, in order.

===EDIT: v7_harness/coord/hud_live.py===
<<<<<<< SEARCH


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
=======


def ensure_flagman(project: Path) -> dict[str, Any]:
    """U304-A: the refresher is the one resident process the user keeps open, so it re-spawns a dead Flagman
    daemon every cycle (a live one costs one PID probe). Hook pulses alone cannot keep the HUD reading LIVE."""
    from ..disjoint_mediator import FLAGMAN_DAEMON_INTERVAL_S, ensure_independent_flagman_daemon

    try:
        return ensure_independent_flagman_daemon(Path(project), interval_s=FLAGMAN_DAEMON_INTERVAL_S)
    except Exception as exc:  # noqa: BLE001 - a failed spawn must not stop the HUD; the page shows STOPPED
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hud_live.py===
<<<<<<< SEARCH

def serve(project: Path, *, once: bool = False, open_page: bool = True, sleep: Callable[[float], None] = time.sleep,
          max_cycles: int | None = None) -> dict[str, Any]:
    project = Path(project).resolve()
    out, pid_file = out_paths(project)
=======

def serve(project: Path, *, once: bool = False, open_page: bool = True, sleep: Callable[[float], None] = time.sleep,
          max_cycles: int | None = None, ensure: Callable[[Path], Any] = ensure_flagman) -> dict[str, Any]:
    project = Path(project).resolve()
    out, pid_file = out_paths(project)
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hud_live.py===
<<<<<<< SEARCH
            os.startfile(str(out))  # noqa: S606 - local page in the default browser
        return {"ok": True, "state": "ALREADY_RUNNING", "pid": other, "html": str(out)}
    snap = render_once(project, out)
    if open_page:
=======
            os.startfile(str(out))  # noqa: S606 - local page in the default browser
        return {"ok": True, "state": "ALREADY_RUNNING", "pid": other, "html": str(out)}
    if not once:
        ensure(project)
    snap = render_once(project, out)
    if open_page:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hud_live.py===
<<<<<<< SEARCH
        cycles += 1
        try:
            render_once(project, out)
        except Exception as exc:  # keep the HUD alive; the error is kept next to the page
=======
        cycles += 1
        try:
            ensure(project)
            render_once(project, out)
        except Exception as exc:  # keep the HUD alive; the error is kept next to the page
>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
