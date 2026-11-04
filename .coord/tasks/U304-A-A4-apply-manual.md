```contract
work_id: U304-A-A4
worker: apply
goal: In v7_harness/disjoint_mediator.py, keep the daemon PID apart from hook pulse writers and make the daemon import the ensuring runtime and exit when superseded.
inputs:
- v7_harness/disjoint_mediator.py sha256=0a8eafe3f718975b749cb7209acaf63317a851c41531d9326fa22b8ac1f6fd58
allow:
- v7_harness/disjoint_mediator.py
acceptance: python -m pytest tests/test_u273_disjoint_traffic_light_mediator.py tests/test_u271_ollama_haiku_disjoint_parallel.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
apply_after: U304-A-L4
```

## Instructions for the worker

worker: local U304-A-L4 failed (ollama unreachable: timed out on the 1400-line file); this applies the same edit.

Apply the blocks below exactly, in order.

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH


def write_flagman_independent_presence(
    project_root: Path,
=======


def flagman_daemon_meta_file(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".coord" / "flagman_daemon.json"


# U304-A: set in the daemon's own environment; a pulse from any other process is a transient hook pulse.
FLAGMAN_DAEMON_ENV = "UAOS_FLAGMAN_DAEMON_PID"


def _recorded_flagman_daemon_pid(root: Path) -> int | None:
    try:
        pid = json.loads(flagman_daemon_meta_file(root).read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        return None
    return pid if isinstance(pid, int) and pid > 0 else None


def _current_pulse_source() -> str:
    return "daemon" if os.environ.get(FLAGMAN_DAEMON_ENV) == str(os.getpid()) else "hook"


def write_flagman_independent_presence(
    project_root: Path,
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
    ttl_s: float = 7200.0,
    pulse_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit the Independent Flagman Entity's own heartbeat to `.coord/presence/flagman.json`.
    Unlike subordinate modules, the Flagman Entity stays `ACTIVE` even when all 3 paid tools
    (Codex, Claude Code, Antigravity) are `LIMITED` or `ABSENT`.
    """
    from datetime import datetime, timezone
=======
    ttl_s: float = 7200.0,
    pulse_summary: dict[str, Any] | None = None,
    pulse_source: str | None = None,
) -> dict[str, Any]:
    """Emit the Independent Flagman Entity's own heartbeat to `.coord/presence/flagman.json`.
    Unlike subordinate modules, the Flagman Entity stays `ACTIVE` even when all 3 paid tools
    (Codex, Claude Code, Antigravity) are `LIMITED` or `ABSENT`.

    U304-A: `pid`/`daemon_pid` name the resident daemon, never the writer. Hook processes also pulse and exit
    seconds later; stamping their PID made `flagman_liveness` read STOPPED/PID_NOT_RUNNING beside a fresh pulse.
    The writer goes to `pulse_pid`/`pulse_source`; `daemon_pid` is null when no daemon was ever recorded.
    """
    from datetime import datetime, timezone
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
    iso_now = datetime.fromtimestamp(moment, timezone.utc).isoformat()
    root = Path(project_root).resolve()

    presence_payload: dict[str, Any] = {
=======
    iso_now = datetime.fromtimestamp(moment, timezone.utc).isoformat()
    root = Path(project_root).resolve()
    source = pulse_source or _current_pulse_source()
    daemon_pid = os.getpid() if source == "daemon" else _recorded_flagman_daemon_pid(root)

    presence_payload: dict[str, Any] = {
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
        "updated_at": moment,
        "expires_at": moment + float(ttl_s),
        "pid": os.getpid(),
        "lease": True,
    }
=======
        "updated_at": moment,
        "expires_at": moment + float(ttl_s),
        "pid": daemon_pid,
        "daemon_pid": daemon_pid,
        "pulse_pid": os.getpid(),
        "pulse_source": source,
        "lease": True,
    }
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH


def validate_daemon_caller_root(root: Path) -> Path:
    p = Path(root).resolve()
=======


def _is_python_pid(pid: int) -> bool:
    """U304-A: a recorded daemon PID reused by another program must not count as the daemon (same rule as the
    HUD's `flagman_liveness`); an unreadable image name is not proof either way, so it is trusted."""
    try:
        from .coord.capacity_planner import _flagman_process_info

        info = _flagman_process_info(pid)
    except Exception:  # noqa: BLE001 - probing is best effort
        return True
    exe = str((info or {}).get("exe") or "").lower()
    return not exe or "python" in Path(exe).name


# U304-A: the HUD and hooks re-ensure at this pace; 30 s matches the HUD refresh and FLAGMAN_STALE_S = 3 pulses.
FLAGMAN_DAEMON_INTERVAL_S = 30.0


def validate_daemon_caller_root(root: Path) -> Path:
    p = Path(root).resolve()
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
    import subprocess
    root = validate_daemon_caller_root(project_root)
    daemon_meta_file = root / ".coord" / "flagman_daemon.json"
    daemon_meta_file.parent.mkdir(parents=True, exist_ok=True)
    if daemon_meta_file.is_file():
=======
    import subprocess
    root = validate_daemon_caller_root(project_root)
    daemon_meta_file = flagman_daemon_meta_file(root)
    daemon_meta_file.parent.mkdir(parents=True, exist_ok=True)
    if daemon_meta_file.is_file():
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
            meta = json.loads(daemon_meta_file.read_text(encoding="utf-8"))
            pid = meta.get("pid")
            if isinstance(pid, int) and _is_flagman_pid_alive(pid):
                return {
                    "ok": True,
=======
            meta = json.loads(daemon_meta_file.read_text(encoding="utf-8"))
            pid = meta.get("pid")
            if isinstance(pid, int) and _is_flagman_pid_alive(pid) and _is_python_pid(pid):
                return {
                    "ok": True,
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
        }

    loop_code = (
        "import time, sys; from pathlib import Path; "
        f"sys.path.insert(0, {repr(str(root))}); "
        "from v7_harness.disjoint_mediator import run_independent_flagman_pulse; "
        f"root = Path({repr(str(root))}); "
        "\nwhile True:\n"
        "    try:\n"
        "        run_independent_flagman_pulse(root, auto_heal=True)\n"
        "    except Exception:\n"
        "        pass\n"
        f"    time.sleep({float(interval_s)})\n"
    )
    creationflags = 0
=======
        }

    # U304-A: import the package this function runs from (the installed `~/.uaos/runtime/<ver>` when `uaos` calls
    # it), not the project checkout, so a reinstall reaches the daemon. It exits when its project disappears or a
    # newer daemon is recorded, so two concurrent ensures never leave two daemons pulsing.
    runtime_root = str(Path(__file__).resolve().parent.parent)
    log_file = str(root / ".coord" / "presence" / "flagman_daemon.log")
    loop_code = (
        "import os, sys, time, traceback; from pathlib import Path\n"
        f"sys.path.insert(0, {runtime_root!r})\n"
        "from v7_harness import disjoint_mediator as dm\n"
        "os.environ[dm.FLAGMAN_DAEMON_ENV] = str(os.getpid())\n"
        f"root = Path({str(root)!r})\n"
        "while (root / '.coord').is_dir():\n"
        "    try:\n"
        "        dm.run_independent_flagman_pulse(root, auto_heal=True)\n"
        "    except Exception:\n"
        "        try:\n"
        f"            open({log_file!r}, 'a', encoding='utf-8').write(traceback.format_exc()[-2000:])\n"
        "        except OSError:\n"
        "            pass\n"
        f"    time.sleep({float(interval_s)})\n"
        "    if dm._recorded_flagman_daemon_pid(root) != os.getpid():\n"
        "        break\n"
    )
    creationflags = 0
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/disjoint_mediator.py===
<<<<<<< SEARCH
        "interval_s": float(interval_s),
        "started_at": time.time(),
        "paid_tokens": 0,
        "local_gpu_tokens": 0,
=======
        "interval_s": float(interval_s),
        "started_at": time.time(),
        "runtime_root": runtime_root,
        "paid_tokens": 0,
        "local_gpu_tokens": 0,
>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
