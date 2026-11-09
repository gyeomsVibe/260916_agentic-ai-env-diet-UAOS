"""Run UAOS-RSI Mobile HUD HTTP Server & ADB Reverse in background."""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from v7_harness.coord.mobile_hud import serve_mobile_api

def setup_adb_reverse():
    adb = Path("C:/platform-tools/adb.exe")
    if adb.is_file():
        try:
            subprocess.run(
                [str(adb), "reverse", "tcp:8765", "tcp:8765"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5
            )
        except Exception:
            pass

def main():
    setup_adb_reverse()
    serve_mobile_api(REPO_ROOT, host="127.0.0.1", port=8765)

if __name__ == "__main__":
    main()
