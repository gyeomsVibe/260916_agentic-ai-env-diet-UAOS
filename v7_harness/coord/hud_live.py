"""U303: live cockpit HUD served from the installed runtime, so every merged HUD change reaches the desktop.

The old desktop icon renders through the Flagman package frozen on 2026-10-29 (`~/.uaos/services/flagman/<id>`,
source f91ed5c plus uncommitted Codex files), so HUD fixes merged after that day never showed. This refresher
imports `capacity_planner` from whatever runtime `uaos` runs (the reinstalled one after each merge) and writes
`<project>/.work/hud_live/cockpit.html` — a separate file, so it never races the Flagman writer of `hud.html`.

One refresher per project: a pid file with a live pid means one already runs; a second launch only opens the page.
Zero paid tokens: it reads local ledgers, rollouts and caches only.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

INTERVAL_S = 30  # Flagman pulses every 30 s and the provider caches change no faster; the page reloads at the same pace
RELOAD_META = '<meta http-equiv="refresh" content="{}" />'.format(INTERVAL_S)


def out_paths(project: Path) -> tuple[Path, Path]:
    live = Path(project) / ".work" / "hud_live"
    return live / "cockpit.html", live / "cockpit.pid.json"


def render_once(project: Path, out: Path) -> dict[str, Any]:
    from .capacity_planner import collect_capacity_snapshot, render_html_dashboard

    snap = collect_capacity_snapshot(Path(project), persist=False)
    tmp = out.with_suffix(f".{os.getpid()}.tmp")
    render_html_dashboard(snap, tmp)
    html = tmp.read_text(encoding="utf-8").replace("<head>", "<head>\n  " + RELOAD_META, 1)
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, out)  # the browser never reads a half-written page
    return snap


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running_refresher(pid_file: Path) -> int | None:
    try:
        pid = int(json.loads(pid_file.read_text(encoding="utf-8")).get("pid"))
    except (OSError, ValueError, TypeError):
        return None
    return pid if _pid_alive(pid) else None


def serve(project: Path, *, once: bool = False, open_page: bool = True, sleep: Callable[[float], None] = time.sleep,
          max_cycles: int | None = None) -> dict[str, Any]:
    project = Path(project).resolve()
    out, pid_file = out_paths(project)
    out.parent.mkdir(parents=True, exist_ok=True)
    other = None if once else running_refresher(pid_file)
    if other is not None:
        if open_page and out.is_file():
            os.startfile(str(out))  # noqa: S606 - local page in the default browser
        return {"ok": True, "state": "ALREADY_RUNNING", "pid": other, "html": str(out)}
    snap = render_once(project, out)
    if open_page:
        os.startfile(str(out))  # noqa: S606
    if once:
        return {"ok": True, "state": "RENDERED", "html": str(out), "generated_at": snap.get("generated_at")}
    pid_file.write_text(json.dumps({"pid": os.getpid(), "started_at": time.time()}), encoding="utf-8")
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        sleep(INTERVAL_S)
        cycles += 1
        try:
            render_once(project, out)
        except Exception as exc:  # keep the HUD alive; the error is kept next to the page
            (out.parent / "cockpit_last_error.txt").write_text(repr(exc), encoding="utf-8")
    return {"ok": True, "state": "STOPPED", "cycles": cycles, "html": str(out)}
