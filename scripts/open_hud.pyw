"""Launch UAOS-RSI Live HUD: immediate browser opening + background live updater."""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
import webbrowser
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1]
    live_dir = root / ".work" / "hud_live"
    live_dir.mkdir(parents=True, exist_ok=True)
    cockpit_file = live_dir / "cockpit.html"
    hud_file = live_dir / "hud.html"

    # Always ensure both cockpit.html and hud.html exist and are up to date
    if cockpit_file.is_file():
        try:
            shutil.copy2(cockpit_file, hud_file)
        except Exception:
            pass

    target = cockpit_file if cockpit_file.is_file() else hud_file

    # 1. Immediately open the browser with file URI and system fallback
    if target.is_file():
        opened = False
        try:
            opened = webbrowser.open(target.resolve().as_uri())
        except Exception:
            pass
        if not opened:
            try:
                os.startfile(str(target))
            except Exception as e:
                (live_dir / "launch_error.txt").write_text(f"open error: {e}\n", encoding="utf-8")

    # 2. Run the updater in background to render and refresh periodically
    try:
        cmd = [sys.executable, "-m", "v7_harness.cli", "coord", "hud", "--project", str(root)]
        subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except Exception as e:
        (live_dir / "launch_error.txt").write_text(f"spawn error: {e}\n", encoding="utf-8")

if __name__ == "__main__":
    main()
