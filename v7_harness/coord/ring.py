"""U143: a real OS sound when a letter that asks for a turn is published, so 윤겸스 hears arrivals.

Receipt: .coord/notes/U134R_U143_MIA_TOTAL_ARCHITECTURE_PROPOSAL.md §1 (letters arrived silently; `sentinel.ring_bell`
only queues text). Windows only: winsound.MessageBeep queues the sound and returns at once
(https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-messagebeep), so a delivery never waits on it.
Elsewhere nothing plays, because a terminal BEL on stdout would corrupt hook JSON.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# One sound per minute: U71 e2e saw six senders publish at once; one sound is enough to notice and a burst must not
# become a siren.
RING_GAP_S = 60
STAMP = Path(".coord") / "ring" / "last.json"


def ring(desk: Path, *, reason: str, env: Any = None, player: Any = None, now: float | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    if env.get("UAOS_WORKER") == "1":
        return {"rung": False, "reason": "WORKER"}  # headless runs are not the user
    if env.get("UAOS_RING", "1") == "0":
        return {"rung": False, "reason": "RING_OFF"}
    if player is None:
        try:
            import winsound
        except ImportError:
            return {"rung": False, "reason": "NO_SOUND_DEVICE"}
        player = lambda: winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)  # noqa: E731
    now = time.time() if now is None else now
    stamp = Path(desk) / STAMP
    try:
        last = float(json.loads(stamp.read_text(encoding="utf-8"))["ts"])
    except (OSError, ValueError, KeyError, TypeError):
        last = 0.0
    if 0 <= now - last < RING_GAP_S:
        return {"rung": False, "reason": "COALESCED"}
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({"ts": now, "reason": reason[:120]}), encoding="utf-8")
        player()
    except Exception as exc:  # a sound must never fail a delivery
        return {"rung": False, "reason": f"ERROR {type(exc).__name__}"}
    return {"rung": True, "reason": reason[:120]}
