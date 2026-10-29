"""Tell one UAOS tool what the other tools changed in a project since it last looked (U103, all three tools)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

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
# U223: a new session's first look lists letters addressed to the tool for a day, not an hour.
# Receipt: a consult letter 72 minutes older than the next session was never shown and the tiki-taka stalled.
# Hidden unacked letters are only counted, with no ids, so a backlog cannot flood the delta.
ADDRESSED_FIRST_LOOK_S = 86400
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

_PAYLOAD_CACHE: dict[tuple[str, int], dict] = {}


def _payload(path: Path) -> dict:
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns)
        cached = _PAYLOAD_CACHE.get(key)
        if cached is not None:
            return cached
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    body = data.get("payload", data)
    res = body if isinstance(body, dict) else {}
    if len(_PAYLOAD_CACHE) > 4096:
        _PAYLOAD_CACHE.clear()
    _PAYLOAD_CACHE[key] = res
    return res

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

def absence_items(
    root: Path,
    since: float,
    tool: str,
    seen_uncommitted: set[str] | None = None,
) -> list[str]:
    root = Path(root)
    tool = canonical(tool)
    items: list[str] = []
    # Commits
    args = ["log", "HEAD", "--no-merges", f"--since=@{int(since)}", "--format=%h %s"]
    if tool in TRAILERS:
        args.extend(["--invert-grep", f"--grep={TRAILERS[tool]}"])
    for line in _git(root, *args):
        items.append(f"commit {line}")
    # Uncommitted (U275: filter by file mtime > since or unseen status line so stale dirty files do not flood every turn)
    for line in _git(root, "-c", "core.quotePath=false", "status", "--porcelain", "--untracked-files=no"):
        entry = f"uncommitted {line.strip()}"
        rel_part = line[3:].split(" -> ")[-1].strip().strip('"')
        target = root / rel_part
        if target.exists():
            if _mtime(target) <= since:
                continue
        elif seen_uncommitted is not None and entry in seen_uncommitted:
            continue
        items.append(entry)
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

def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _addressed_to(path: Path, tool: str) -> bool:
    body = _payload(path)
    return canonical(body.get("requested_target") or body.get("to") or "") == tool

def _first_look_addressed(letter: Path, inbox: Path, tool: str, now: float) -> str | None:
    """U223: an unacked letter to the tool is "fresh" for a day, then "backlog"."""
    if not _addressed_to(letter, tool) or (inbox.parent / "ack" / letter.name).exists():
        return None
    return "fresh" if _mtime(letter) > now - ADDRESSED_FIRST_LOOK_S else "backlog"


def ack_receipts(project: Path, tool: str, letters: list[Path]) -> None:
    """U141-A: retire the wake receipts of letters the hook really showed, so no later watcher wakes for them.

    A pending receipt moves to acked; a letter shown while no watcher ran gets an acked record directly.
    """
    from v7_harness.coord import watch as W

    if tool not in W.TOOLS:
        return
    for letter in letters:
        if not _addressed_to(letter, tool):
            continue
        digest = W.letter_digest(letter.stem, _payload(letter))
        pending = W.pending_wake_path(project, tool, digest)
        acked = W.acked_wake_path(project, tool, digest)
        acked.parent.mkdir(parents=True, exist_ok=True)
        if acked.is_file():
            pending.unlink(missing_ok=True)
            continue
        if pending.is_file() and W._receipt_state(pending, time.time) == "CORRUPT":
            continue  # kept as evidence; the hook keeps naming it
        if pending.is_file():
            W.replace_with_retry(pending, acked)
        else:
            W._write_atomic(acked, {"target": tool, "message_id": letter.stem, "digest": digest,
                                    "acked_at": time.time(), "via": "desk_delta"})


def _receipt_findings(project: Path, tool: str) -> tuple[list[str], dict[str, str]]:
    """Corrupt receipt names, and the message id of each readable pending receipt (for crash recovery)."""
    from v7_harness.coord import watch as W

    corrupt: list[str] = []
    pending: dict[str, str] = {}
    if tool not in W.TOOLS:
        return corrupt, pending
    folder = Path(project) / W.PRESENCE_DIR / "pending_wake" / tool
    if not folder.is_dir():
        return corrupt, pending
    for path in sorted(folder.glob("*.json")):
        state = W._receipt_state(path, time.time)
        if state == "CORRUPT":
            corrupt.append(path.name)
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a fresh placeholder; its writer completes it
        if isinstance(record, dict) and isinstance(record.get("message_id"), str):
            pending[record["message_id"]] = path.name
    return corrupt, pending


def _wake_note(path: Path) -> str:
    from v7_harness.coord import watch as W

    body = _payload(path)
    if not any(key in body for key in W.STRUCTURED_FIELDS):
        return ""
    cls, diag = W.classify(body)
    return f" [wake INVALID: {diag}]" if cls == "INVALID" else ""


def _replay_bound(project: Path, tool: str, session: str | None, letter: Path, memo: dict | None = None) -> bool:
    if not session or tool not in TOOLS or not _addressed_to(letter, tool):
        return False
    body = _payload(letter)
    bound = body.get("native_receiver") or body.get("window")
    if bound and bound != session:
        return False
    card = body.get("card", "")
    if not isinstance(card, str):
        return False
    try:
        if card:
            from .windows import window_for
            return window_for(project, card, tool) == session
        from .desk_sync import desk_identity
        memo = {} if memo is None else memo
        if "desk" not in memo:
            memo["desk"] = desk_identity(project, tool)
        status, identity = memo["desk"]
        return status == "PROJECT_BOUND" and identity.get("thread") == session
    except (OSError, ValueError, TypeError):
        return False


def _replay_letters(project: Path, tool: str, session: str | None) -> list[Path]:
    if not session or tool not in TOOLS:
        return []
    from .mailbox import _is_symlink_or_reparse
    inbox = project / ".coord" / "mailbox" / "inbox"
    if not inbox.is_dir():
        return []
    acked = inbox.parent / "ack"
    acked_names = {p.name for p in acked.glob("*.json")} if acked.is_dir() else set()
    ordered = []
    memo: dict = {}
    for letter in inbox.glob("*.json"):
        try:
            if letter.name in acked_names or not letter.is_file() or _is_symlink_or_reparse(letter):
                continue
            if own_letter(letter, tool) or not _replay_bound(project, tool, session, letter, memo):
                continue
            ordered.append((letter.stat().st_mtime_ns, letter.name, letter))
        except (OSError, ValueError):
            continue
    return [entry[2] for entry in sorted(ordered)]


def _replay_urgent(letter: Path) -> bool:
    body = _payload(letter)
    return body.get("kind") == "P1" or body.get("p1_alert") is True or body.get("verdict_requested") is True


def prepare_delta(project: Path, tool: str, session: str | None = None,
                  now: float | None = None) -> tuple[str, Callable[[], None]]:
    """U141-A: build the delta text without advancing anything; call the returned ack() only after it was written.

    Only the first MAX_LINES items count as shown. Unshown letters stay in the cursor's `unshown` list and lead the
    next delta, so the digest cap never starves a letter, and only shown letters get their wake receipts acked.
    """
    project = Path(project)
    tool = canonical(tool)
    now = time.time() if now is None else float(now)
    path = cursor_path(project, tool, session)
    try:
        cursor = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cursor = None
    had_cursor = isinstance(cursor, dict)
    if not had_cursor:
        cursor = {}
    since = float(cursor.get("since", now - FIRST_LOOK_S))
    seen = cursor.get("plan", {})
    unshown_before = [name for name in cursor.get("unshown", []) if isinstance(name, str)] \
        if isinstance(cursor.get("unshown"), list) else []
    items: list[tuple[str, Path | None]] = []
    replay = _replay_letters(project, tool, session)
    if replay:
        head = replay[0]
        items.append((f"RESUME_PENDING {head.stem}: read stored letter, process in order; coord ack only after disposition. {summary_of(head)}", head))
    # U163: a peer's user-desk change leads the delta; its cursor advances in ack(), after the text was written.
    from v7_harness.coord import desk_sync

    notice, notice_ack = desk_sync.prepare_notice(project, tool, session)
    items.extend((line, None) for line in notice.splitlines())
    corrupt, pending = _receipt_findings(project, tool)
    for name in corrupt:
        items.append((f"CORRUPT_WAKE_RECEIPT {name}: kept; no automatic wake", None))
    rows = plan_rows(project / ".coord" / "PLAN.md")
    for key, status in rows.items():
        if key in seen and seen[key] != status:
            items.append((f"PLAN {key}: {seen[key]} -> {status}", None))
    # Pilot run events (`evt_*`) collapse to one counted line per tool, newest shown; relays and git changes come first.
    events: dict[str, list[Path]] = {}
    inbox = project / ".coord" / "mailbox" / "inbox"
    letters: list[Path] = []
    recovered: list[Path] = []
    hidden = 0
    if inbox.is_dir():
        for letter in sorted(inbox.glob("*.json")):
            if letter in replay and (letter == replay[0] or not _replay_urgent(letter)):
                hidden += letter != replay[0]
                continue
            if not letter.is_file():
                continue
            mtime = _mtime(letter)
            in_replay = letter in replay
            in_unshown = letter.stem in unshown_before
            if had_cursor and mtime <= since and not in_replay and not in_unshown:
                if letter.stem in pending and not own_letter(letter, tool):
                    from .stop_gate import _foreign
                    if not _foreign(project, tool, session, _payload(letter)):
                        recovered.append(letter)
                continue
            if own_letter(letter, tool):
                continue
            from .stop_gate import _foreign
            if _foreign(project, tool, session, _payload(letter)):
                continue
            fresh = mtime > since or (in_replay and _replay_urgent(letter))
            look = None if fresh or in_unshown else _first_look_addressed(letter, inbox, tool, now)
            fresh = fresh or (look == "fresh" and not had_cursor)
            hidden += look is not None and not fresh
            if not fresh and not in_unshown:
                # U141-A crash recovery: shown before (cursor written) but its receipt was never acked.
                if had_cursor and letter.stem in pending:
                    recovered.append(letter)
                continue
            if letter.name.startswith("evt_"):
                events.setdefault(canonical(_payload(letter).get("actor", "")) or "unknown", []).append(letter)
            else:
                letters.append(letter)
    letters.sort(key=lambda p: (p.stem not in unshown_before, _mtime(p), p.name))
    urgent_items = []
    for letter in letters:
        item = (f"letter {letter.stem}{_wake_note(letter)}: {summary_of(letter)}", letter)
        if letter in replay and _replay_urgent(letter):
            urgent_items.append(item)
        else:
            items.append(item)
    items[1:1] = urgent_items
    if hidden:
        items.insert(min(len(items), MAX_LINES - 1), (f"UNACKED_BACKLOG {hidden} letter(s) to {tool}: run coord inbox, dispose, coord ack", None))
    seen_uncom = (
        {s for s in cursor.get("uncommitted", []) if isinstance(s, str)}
        if had_cursor and isinstance(cursor.get("uncommitted"), list)
        else None
    )
    items.extend((item, None) for item in absence_items(project, since, tool, seen_uncommitted=seen_uncom))
    for actor, group in events.items():
        items.append((f"{len(group)} run event(s) from {actor}, newest {group[-1].stem}: {summary_of(group[-1])}", None))
    shown = [letter for _text, letter in items[:MAX_LINES] if letter is not None]
    unshown = [letter.stem for _text, letter in items[MAX_LINES:] if letter is not None]
    text = ""
    if items:
        lines = [f"DESK DELTA for {tool} ({len(items)} items since your last look): audit each before new work; the user must not have to paste it (U103)."]
        for item, _letter in items[:MAX_LINES]:
            lines.append(f"- {item[:SNIPPET]}")
        if len(items) > MAX_LINES:
            lines.append(f"- ... {len(items) - MAX_LINES} more not shown")
        text = "\n".join(lines)

    def ack() -> None:
        # The cursor first (atomic), then the receipts: a crash between them is completed by the next hook (recovery).
        cur_uncom = [
            f"uncommitted {l.strip()}"
            for l in _git(project, "-c", "core.quotePath=false", "status", "--porcelain", "--untracked-files=no")
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(
            json.dumps({"since": now, "plan": rows, "unshown": unshown, "uncommitted": cur_uncom}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        ack_receipts(project, tool, shown + recovered)
        notice_ack()

    return text, ack


def delta_text(project: Path, tool: str, session: str | None = None, now: float | None = None) -> str:
    """The pre-U141-A behaviour: build and advance at once."""
    text, ack = prepare_delta(project, tool, session, now)
    ack()
    return text
