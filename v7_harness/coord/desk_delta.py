"""Tell one UAOS tool what the other tools changed in a project since it last looked (U103, all three tools)."""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

# The three desks; Antigravity's hooks call it "agy".
TOOLS = ("claude", "codex", "antigravity")
ALIASES = {"agy": "antigravity"}
# Each tool signs its commits with this trailer; its own commits are not news to it.
TRAILERS = {"claude": "Co-Authored-By: Claude", "codex": "Co-Authored-By: Codex",
            "antigravity": "Co-Authored-By: Antigravity"}
# Folders where a tool leaves reports, memos and manuals.
FILE_FOLDERS = (".coord/tasks", ".coord/notes")
# git must answer fast inside a prompt hook.
GIT_TIMEOUT_S = 10
# Without a cursor, look back one hour.
FIRST_LOOK_S = 3600
# Keeps the injected context short; the rest is counted, not dropped silently.
MAX_LINES = 12
# Characters of each item shown; the path gives the rest.
SNIPPET = 220

def canonical(tool: str) -> str:
    name = str(tool or "").strip().lower()
    return ALIASES.get(name, name)

def _git(root: Path, *args: str) -> list[str]:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]

def _epoch(stamp) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None

def _payload(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    body = data.get("payload", data)
    return body if isinstance(body, dict) else {}

def own_letter(path: Path, tool: str) -> bool:
    tool = canonical(tool)
    name = path.name.lower()
    return name.startswith(f"{tool}_to_") or tool in name.split("-") or canonical(_payload(path).get("actor", "")) == tool

def summary_of(path: Path) -> str:
    body = _payload(path)
    text = str(body.get("summary") or body.get("verdict") or body.get("message") or path.name)
    return " ".join(text.split())[:SNIPPET]

def plan_rows(path: Path) -> dict[str, str]:
    rows = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("| ") and line.count("|") >= 4:
                cells = line.split("|")
                rows[cells[1].strip()] = cells[2].strip()
    except OSError:
        pass
    return rows

def absence_items(root: Path, since: float, tool: str) -> list[str]:
    root = Path(root)
    tool = canonical(tool)
    items: list[str] = []
    # Commits
    args = ["log", "--all", "--no-merges", f"--since=@{int(since)}", "--format=%h %s"]
    if tool in TRAILERS:
        args.extend(["--invert-grep", f"--grep={TRAILERS[tool]}"])
    for line in _git(root, *args):
        items.append(f"commit {line}")
    # Uncommitted
    for line in _git(root, "status", "--porcelain", "--untracked-files=no"):
        items.append(f"uncommitted {line.strip()}")
    # Leases
    presence = root / ".coord" / "presence"
    if presence.is_dir():
        for path in sorted(presence.glob("*.json")):
            other = path.stem
            if other not in TOOLS or other == tool:
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("lease") is not True:
                continue
            observed = _epoch(record.get("observed_at"))
            if observed is None or observed <= since:
                continue
            items.append(f"lease {other} {record.get('state')} observed {record.get('observed_at')}")
    # Files
    tracked = set(_git(root, "ls-files", "--", *FILE_FOLDERS))
    for folder in FILE_FOLDERS:
        base = root / folder
        if base.is_dir():
            for path in sorted(base.glob("*")):
                if path.is_file() and path.stat().st_mtime > since and f"{folder}/{path.name}" not in tracked:
                    items.append(f"file {folder}/{path.name}")
    return items

def cursor_path(project: Path, tool: str, session: str | None) -> Path:
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", str(session or "default")) or "default"
    return Path(project) / ".coord" / "presence" / f"desk_delta_{canonical(tool)}_{clean}.json"

def delta_text(project: Path, tool: str, session: str | None = None, now: float | None = None) -> str:
    project = Path(project)
    tool = canonical(tool)
    now = time.time() if now is None else float(now)
    path = cursor_path(project, tool, session)
    try:
        cursor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cursor = {}
    if not isinstance(cursor, dict):
        cursor = {}
    since = float(cursor.get("since", now - FIRST_LOOK_S))
    seen = cursor.get("plan", {})
    items: list[str] = []
    rows = plan_rows(project / ".coord" / "PLAN.md")
    for key, status in rows.items():
        if key in seen and seen[key] != status:
            items.append(f"PLAN {key}: {seen[key]} -> {status}")
    # Pilot run events (`evt_*`) collapse to one counted line per tool, newest shown; relays and git changes come first.
    events: dict[str, list[Path]] = {}
    inbox = project / ".coord" / "mailbox" / "inbox"
    if inbox.is_dir():
        for letter in sorted(inbox.glob("*.json")):
            if not letter.is_file() or letter.stat().st_mtime <= since or own_letter(letter, tool):
                continue
            if letter.name.startswith("evt_"):
                events.setdefault(canonical(_payload(letter).get("actor", "")) or "unknown", []).append(letter)
            else:
                items.append(f"letter {letter.stem}: {summary_of(letter)}")
    items.extend(absence_items(project, since, tool))
    for actor, group in events.items():
        items.append(f"{len(group)} run event(s) from {actor}, newest {group[-1].stem}: {summary_of(group[-1])}")
    # Write the cursor
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"since": now, "plan": rows}, ensure_ascii=False), encoding="utf-8")
    if not items:
        return ""
    lines = [f"DESK DELTA for {tool} ({len(items)} items since your last look): audit each before new work; the user must not have to paste it (U103)."]
    for item in items[:MAX_LINES]:
        lines.append(f"- {item[:SNIPPET]}")
    if len(items) > MAX_LINES:
        lines.append(f"- ... {len(items) - MAX_LINES} more not shown")
    return "\n".join(lines)
