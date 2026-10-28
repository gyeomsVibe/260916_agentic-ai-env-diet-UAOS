"""U286: live HUD for the desktop icon — refresh the dashboard HTML in the background, open it once.

Run with pythonw (no console window). One refresher per project: a dashboard file written within
the last STALE_S seconds means a refresher already runs, so a second click only opens the page.
Zero paid tokens: it only reads local ledgers/presence files through collect_capacity_snapshot.
Usage: pythonw uaos_hud_live.pyw --project <UAOS project root>
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v7_harness.coord.capacity_planner import collect_capacity_snapshot, render_html_dashboard  # noqa: E402

INTERVAL_S = 30  # Flagman pulses every 30 s; refreshing faster shows nothing new.
STALE_S = 3 * INTERVAL_S  # three missed refreshes = no refresher alive
RELOAD_META = '<meta http-equiv="refresh" content="{}" />'.format(INTERVAL_S)


def render(project: Path, out: Path) -> None:
    render_html_dashboard(collect_capacity_snapshot(project, persist=False), out)
    html = out.read_text(encoding="utf-8").replace("<head>", "<head>\n  " + RELOAD_META, 1)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, out)  # the browser never reads a half-written page


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    out = project / ".work" / "hud_live" / "hud.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    running = out.exists() and time.time() - out.stat().st_mtime < STALE_S
    if not running:
        render(project, out)
    os.startfile(out)  # noqa: S606 - opens the local page in the default browser
    if running:
        return 0
    while True:
        time.sleep(INTERVAL_S)
        try:
            render(project, out)
        except Exception as exc:  # keep the HUD alive; the error shows on the next good render
            (out.parent / "last_error.txt").write_text(repr(exc), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
