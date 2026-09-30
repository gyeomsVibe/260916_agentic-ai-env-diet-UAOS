"""Claude UserPromptSubmit hook: surface what Codex wrote since Claude last looked, so the user never pastes it.

Why (2026-09-27): Codex judged U48-J1 into `.work/u45_claude/.coord/tasks/*.md` and PLAN.md but sent no mailbox
letter, and Claude only read the main repo's `.coord/mailbox/inbox`. The user had to paste Codex's reply twice.
This hook reads every place Codex writes (both mailbox roots, task records, PLAN rows) and prints only the delta.

Deterministic, read-only on the project, 0 model tokens. Cursor: ~/.uaos/hooks/codex_delta_cursor.json.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path("D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet")
# The main checkout and the worktree each hold a .coord; Codex has written to both.
COORDS = [ROOT / ".coord", ROOT / ".work" / "u45_claude" / ".coord"]
CURSOR = Path.home() / ".uaos" / "hooks" / "codex_delta_cursor.json"
MAX_LINES = 12  # keeps the injected context short; the rest is counted, not dropped silently
SNIPPET = 220  # characters of each item shown; enough for a summary line, the path gives the rest


def cursor_for(session_id: str | None) -> Path:
    if not session_id:
        return CURSOR
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(session_id).name) or "default"
    return CURSOR.parent / f"codex_delta_cursor_{clean}.json"


def load_cursor(path: Path | None = None) -> dict:
    target = path or CURSOR
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def summary_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            data = json.loads(text)
            body = data.get("payload", data)
            text = str(body.get("summary") or body.get("verdict") or body.get("message") or text)
        except (ValueError, AttributeError):
            pass
    else:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        text = " ".join(lines[:3])
    return " ".join(text.split())[:SNIPPET]


def actor_of(path: Path) -> str:
    """Who wrote a JSON letter (`payload.actor`), or "" when the file says nothing readable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return str(data.get("payload", data).get("actor") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def plan_rows(path: Path) -> dict[str, str]:
    rows = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("| ") and line.count("|") >= 4:
                key = line.split("|")[1].strip()
                rows[key] = line.split("|")[2].strip()
    except OSError:
        pass
    return rows


def main() -> int:
    session_id = None
    try:
        if not getattr(sys.stdin, "isatty", lambda: True)():
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    session_id = payload.get("session_id")
    except (OSError, ValueError, AttributeError):
        pass

    cursor_path = cursor_for(session_id)
    cursor = load_cursor(cursor_path)
    since = float(cursor.get("since", time.time() - 3600))
    seen_rows = cursor.get("plan", {})
    items = []
    for coord in COORDS:
        for folder, pattern in ((coord / "mailbox" / "inbox", "*.json"), (coord / "tasks", "*")):
            if not folder.is_dir():
                continue
            for path in folder.glob(pattern):
                if not path.is_file() or path.stat().st_mtime <= since:
                    continue
                name = path.name.lower()
                # U102-N: 240 of Claude's own evt letters carry "-claude-" mid-name; its relays say so only in actor.
                own = name.startswith("claude_to_") or "claude" in name.split("-")[0] or "claude" in name.split("-")
                if own or (path.suffix == ".json" and actor_of(path) == "claude"):
                    continue  # Claude's own letters are not news to Claude
                if folder.name == "tasks" and "codex" not in name and "judgement" not in name and "review" not in name:
                    continue
                items.append((path.stat().st_mtime, f"{path.relative_to(ROOT).as_posix()}: {summary_of(path)}"))
    new_rows = {}
    for coord in COORDS:
        for key, status in plan_rows(coord / "PLAN.md").items():
            tag = f"{coord.parent.name}:{key}"
            new_rows[tag] = status
            if tag in seen_rows and seen_rows[tag] != status:
                items.append((time.time(), f"PLAN {key} ({coord.parent.name}): {seen_rows[tag]} -> {status}"[:SNIPPET]))
    items.sort()
    # U101: letters and PLAN rows missed direct commits, hand-written leases and uncommitted edits (U100 audit).
    try:
        from absence_brief import absence_items  # deployed next to this hook in ~/.uaos/hooks
    except ImportError:
        from uaos_everywhere.hooks.absence_brief import absence_items
    others = absence_items(ROOT, since)
    if others:
        print(f"OTHER TOOLS CHANGED since your last prompt ({len(others)} items): audit each before new work;"
              " the user must not have to ask (U101).")
        for line in others[:MAX_LINES]:
            print(f"- {line[:SNIPPET]}")
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(json.dumps({"since": time.time(), "plan": new_rows}, ensure_ascii=False), encoding="utf-8")
    if not items:
        return 0  # ACK_ONLY: nothing new, stay silent
    print(f"CODEX DELTA since last prompt ({len(items)} items; read these before acting, do not ask the user to paste):")
    for _, line in items[-MAX_LINES:]:
        print(f"- {line}")
    if len(items) > MAX_LINES:
        print(f"- ... {len(items) - MAX_LINES} older items not shown")
    return 0


if __name__ == "__main__":
    # The hook's stdout reached Claude as CP949 mojibake for Korean PLAN rows (2026-09-27); force UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        sys.exit(main())
    except Exception as exc:  # a hook must never block the prompt
        print(f"codex_delta hook error: {exc}")
        sys.exit(0)
