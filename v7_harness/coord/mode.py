"""U95-T: token-thrift is UAOS-RSI's default operating mode, read by code and not only written in the rules.

Receipt (윤겸스, 2026-09-30): with today's habits one Claude or Codex conversation drains a 5-hour or weekly limit
before one process, let alone a project, is done. The goal is a much longer workflow on the same budget, and
token-thrift is the default mode. The rules said "Token-thrift is default" since v6, yet no code read a mode, so
nothing changed when a card overspent. This module is the one place the runtime asks which mode is on:

- Token-thrift unless `.coord/mode.json` holds {"mode": "normal", "set_by": "user", "reason": "..."}. A missing,
  unreadable or different file keeps token-thrift (fail-thrift): only 윤겸스's explicit instruction ends it, and the
  file is a reviewed commit, so the switch is visible in history.
- In token-thrift a card may spend at most its share, SHARE_LIMIT times the pinned baseline card average
  (`card_cost`); over it the card is split, not continued. Normal mode keeps only the 3x regression rule.

Not to be confused with `coord thrift` (U63, `thrift.py`): that is a handoff ladder over an observed remaining-quota
percentage (its NORMAL/THRIFT/HANDOFF_READY states decide reserves and handoff packets). It runs inside this mode;
its NORMAL state means "no handoff needed", never "token-thrift is off".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODE_FILE = Path(".coord") / "mode.json"
THRIFT = "token-thrift"
NORMAL = "normal"
# The yardstick as a number: a card may cost what the average pinned baseline card cost (.coord/card_baseline.json).
# It is the line a card must not cross, not the target: the U95 success signal asks for 30% below that average.
SHARE_LIMIT = 1.0
# Said once per session start (Claude, Codex) or conversation (Antigravity): about 20 tokens, never per prompt.
THRIFT_PHRASE = "Mode: token-thrift (default): cut paid calls, tool output and idle gaps."


def current_mode(project: Path | str) -> dict[str, Any]:
    """{"mode", "source"[, "reason"]}; anything but an explicit user switch to normal is token-thrift."""
    path = Path(project) / MODE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"mode": THRIFT, "source": "default"}
    except (OSError, ValueError):
        return {"mode": THRIFT, "source": "unreadable"}
    if not isinstance(data, dict):
        return {"mode": THRIFT, "source": "invalid"}
    reason = data.get("reason")
    if (data.get("mode") == NORMAL and data.get("set_by") == "user" and isinstance(reason, str)
            and reason.strip()):
        return {"mode": NORMAL, "source": MODE_FILE.as_posix(), "reason": reason.strip()}
    return {"mode": THRIFT, "source": MODE_FILE.as_posix() if data.get("mode") == THRIFT else "invalid"}


def mode_phrase(project: Path | str) -> str:
    mode = current_mode(project)
    if mode["mode"] == NORMAL:
        return f"Mode: normal, set by 윤겸스 ({mode['reason'][:80]})."
    return THRIFT_PHRASE


def over_share(project: Path | str, ratios: dict[str, float]) -> list[str]:
    """Metrics whose ratio to the baseline card average exceeds the share; empty outside token-thrift."""
    if current_mode(project)["mode"] != THRIFT:
        return []
    return [metric for metric, ratio in ratios.items() if ratio > SHARE_LIMIT]
