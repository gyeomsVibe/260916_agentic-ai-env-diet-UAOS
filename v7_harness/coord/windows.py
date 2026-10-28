"""U114: one process (card) gets one dedicated, named window in each tool: Codex app-server thread, Claude desktop
session (U129: recorded, never `claude --bg`), Antigravity conversation. The record `.coord/windows/<card>.json` maps the card to each tool's window id.
U279: Topic-grouped bounded window pool (`normalize_topic_key`, `window_for_topic`, `acquire_topic_window`) across
Codex, Claude Code, and Antigravity to group related sub-tasks into a single window and cap active windows per tool."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.presence import read as read_presence

# A card id becomes a file name: no separators, spaces or "..", so a record never lands outside .coord/windows.
CARD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# The three tools that own windows; Ollama is a calculator and has none.
TOOLS = ("codex", "claude", "antigravity")
# Antigravity answers the opening prompt before it prints the conversation id; one long card turn fits in 15 minutes.
AGY_TIMEOUT_S = 900
# U127: a record read or replace retries with 10 ms, 20 ms, ... back-off (about 2 s over 20 tries) while a parallel
# writer swaps it; the parallel test (8 threads x 10 writes) hit PermissionError on the first try without it.
RECORD_TRIES = 20
# U279: bounded active topic window pool per tool to prevent window proliferation (대화창 남발 방지).
MAX_ACTIVE_WINDOWS_PER_TOOL = 3
# U127 / U279: maximum input tokens before a topic conversation window is rotated to a fresh window.
RESUME_MAX_INPUT = 70_000
_CARD_FAMILY_RE = re.compile(r"(?:^|[^A-Za-z0-9])(U\d{2,4})(?=$|[^0-9])", re.IGNORECASE)
_SUBSTEP_SUFFIX_RE = re.compile(
    r"(?:[-_.](?:R\d+|L\d+|V\d+|A\d+|S\d+|STAGE\d*|FIX\d*|SLICE\d*|VERDICT|MANUAL|AUDIT|RETRY\d*|SPEC|\d{6,8}))+$",
    re.IGNORECASE,
)
_DESK_SYNC_RE = re.compile(r"^(?:CODEX[-_]RETURN|DESK[-_]|HANDOFF[-_]|RETURN[-_])", re.IGNORECASE)
_RSI_STREAM_RE = re.compile(r"^RSI[-_]", re.IGNORECASE)
_REVIEW_STREAM_RE = re.compile(r"^(?:REVIEW|AUDIT)[-_]", re.IGNORECASE)


# U129: a Claude window is a visible desktop session; its id is the Claude Code session UUID that `--resume` takes
# (CLAUDE_CODE_SESSION_ID inside that session). A banner prefix or a sidebar title is not one.
SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# U129: `claude --bg` sessions never show in the desktop app (docs agent-view), so nothing is launched; since
# 2026-10-02 every route is clickless (send_message into an idle visible session, never a task chip).
NO_VISIBLE_SESSION = ("a Claude card window is an idle visible Claude desktop session: the conductor sends it the "
                      "card with send_message and records it with `uaos coord window --card {card} --tool claude "
                      "--title <title> --session-id <session uuid>`; with no idle session `uaos coord window "
                      "--card {card} --tool auto` routes the card to Codex (ACTIVE) or Antigravity headless")
# U129: one desktop session works one card at a time, so a session held by another unreleased card is refused.
SESSION_BUSY = ("Claude desktop session {session} still holds card {holder}; the conductor releases it with "
                "`uaos coord window --card {holder} --tool claude --title <title> --release` or routes this card "
                "with `--tool auto`")


def normalize_topic_key(card: str, message: str = "") -> str:
    """U279: normalize a sub-card, retry, PR tag, or message prefix into a canonical topic key so related tasks share
    one window instead of spawning separate windows per micro-step (대화창 남발 방지)."""
    raw = (card or "").strip()
    if raw:
        if ".." in raw or not CARD_RE.fullmatch(raw):
            raise ValueError(f"bad card id: {card!r}")
        match = _CARD_FAMILY_RE.search(raw)
        if match:
            return match.group(1).upper()
        if _DESK_SYNC_RE.search(raw):
            return "DESK-SYNC"
        if _RSI_STREAM_RE.search(raw):
            return "RSI-STREAM"
        if _REVIEW_STREAM_RE.search(raw):
            return "REVIEW-STREAM"
        stripped = _SUBSTEP_SUFFIX_RE.sub("", raw).strip("-_.")
        if stripped and CARD_RE.fullmatch(stripped):
            return stripped.upper()
        return raw
    if message:
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), "")
        match = _CARD_FAMILY_RE.search(first_line[:120])
        if match:
            return match.group(1).upper()
        if _DESK_SYNC_RE.search(first_line[:60]):
            return "DESK-SYNC"
    return ""


def window_title(card: str, title: str) -> str:
    return f"[{card}] {title}"


def _record_path(project: Path, card: str) -> Path:
    if not CARD_RE.fullmatch(card or "") or ".." in card:
        raise ValueError(f"bad card id: {card!r}")
    return Path(project) / ".coord" / "windows" / f"{card}.json"


def _retry(op: Callable[[], Any]) -> Any:
    """U127: Windows refuses to open or replace a record while a parallel writer swaps it; retry with back-off."""
    for attempt in range(RECORD_TRIES):
        try:
            return op()
        except PermissionError:
            if attempt == RECORD_TRIES - 1:
                raise
            time.sleep(0.01 * (attempt + 1))


def _load(path: Path) -> dict[str, Any]:
    return _retry(lambda: json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}


def claude_session(short: str) -> tuple[str, str]:
    """U115 judge: a U114 window record may hold an id prefix, but `--resume` needs the full id, and the transcript moves with a
    session that entered a worktree. Return (full id, latest cwd) from the one transcript `<prefix>*.jsonl` under
    `$CLAUDE_CONFIG_DIR` (default ~/.claude) `/projects/*/`; with none or several matches return (short, "")."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = sorted((home / "projects").glob(f"*/{short}*.jsonl"))
    if len(found) != 1:
        return short, ""
    cwd = ""
    with found[0].open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("cwd"):
                cwd = str(row["cwd"])
    return found[0].stem, cwd


def claude_session_identity(thread: str) -> tuple[str, str]:
    """U190-A strict native identity (Codex REVISE relay_b1204616: a file name is not a session).

    ("OK", latest cwd) only when the claude_session lookup finds exactly one transcript, its name is the thread, at
    least one row carries a sessionId and every sessionId is the thread; ("UNREADABLE", "") on a read error;
    ("UNVERIFIED", "") otherwise."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        found = sorted((home / "projects").glob(f"*/{thread}*.jsonl"))
        if len(found) != 1 or found[0].stem != thread:
            return "UNVERIFIED", ""
        cwd, named = "", False
        with found[0].open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("sessionId") is not None:
                    if row["sessionId"] != thread:
                        return "UNVERIFIED", ""
                    named = True
                if row.get("cwd"):
                    cwd = str(row["cwd"])
    except OSError:
        return "UNREADABLE", ""
    return ("OK", cwd) if named else ("UNVERIFIED", "")


def window_for(project: Path, card: str, tool: str) -> str | None:
    exact = _load(_record_path(project, card)).get("tools", {}).get(tool, {})
    if exact.get("id") and not exact.get("released_at"):
        return str(exact["id"])
    # U279: if `card` is a derived sub-card (e.g. `U275-R8-L1`, `PR244-U275`), automatically reuse the canonical
    # topic window (`U275`) so sub-tasks do not fall back to the primary user desk or demand separate windows.
    topic = normalize_topic_key(card)
    if topic and topic != card:
        topic_entry = _load(_record_path(project, topic)).get("tools", {}).get(tool, {})
        if topic_entry.get("id") and not topic_entry.get("released_at"):
            return str(topic_entry["id"])
    return exact.get("id") if exact.get("id") else None


def window_entry(project: Path, card: str, tool: str) -> dict[str, Any]:
    """U127: the card's window entry for one tool ({} when there is none)."""
    return dict(_load(_record_path(project, card)).get("tools", {}).get(tool) or {})


def window_entry_for_topic(project: Path, card: str, tool: str) -> tuple[str, dict[str, Any]]:
    """U279: return `(resolved_topic_or_card, entry)` checking the exact card first, then its canonical `topic_key`."""
    exact = window_entry(project, card, tool)
    if exact.get("id") and not exact.get("released_at"):
        return card, exact
    topic = normalize_topic_key(card)
    if topic and topic != card:
        topic_entry = window_entry(project, topic, tool)
        if topic_entry.get("id") and not topic_entry.get("released_at"):
            return topic, topic_entry
    return (topic or card), exact


def window_for_topic(project: Path, card: str, tool: str) -> str | None:
    """U279: resolve an active window ID for `card` or its canonical `topic_key`."""
    _, entry = window_entry_for_topic(project, card, tool)
    if entry.get("id") and not entry.get("released_at"):
        return str(entry["id"])
    return None


def record_window(project: Path, card: str, tool: str, window_id: str, *, now: float | None = None,
                  **extra: Any) -> dict[str, Any]:
    """U127: write one tool's window for a card and keep the other tools' windows (the U114 record format)."""
    path = _record_path(project, card)
    record = _load(path)
    ts = time.time() if now is None else now
    entry = {"id": window_id, "opened_at": ts, "last_active_at": ts, **extra}
    old = record.get("tools", {}).get(tool) or {}
    if old.get("id") == window_id and "opened_at" in old:
        entry["opened_at"] = old["opened_at"]
    if "subcards" in old and "subcards" not in extra:
        entry["subcards"] = old["subcards"]
    record = {"card": card, "title": record.get("title") or f"[{card}]", "tools": {**record.get("tools", {}), tool: entry}}
    path.parent.mkdir(parents=True, exist_ok=True)
    # U127-A audit: each writer has its own temp file, so two letters for one card never swap a half-written record.
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        _retry(lambda: tmp.replace(path))
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise
    return entry


def active_topic_windows(project: Path, tool: str) -> list[dict[str, Any]]:
    """U279: return all active (unreleased) windows for `tool` across `.coord/windows/*.json`, ordered oldest-active
    first (LRU order) for deterministic pool-cap eviction or least-loaded sharing."""
    win_dir = Path(project) / ".coord" / "windows"
    if not win_dir.is_dir():
        return []
    active: list[dict[str, Any]] = []
    for path in sorted(win_dir.glob("*.json")):
        rec = _load(path)
        entry = (rec.get("tools") or {}).get(tool)
        if not isinstance(entry, dict) or not entry.get("id") or entry.get("released_at"):
            continue
        active.append({
            "card": str(rec.get("card") or path.stem),
            "topic_key": normalize_topic_key(str(rec.get("card") or path.stem)),
            "id": str(entry["id"]),
            "opened_at": float(entry.get("opened_at") or 0.0),
            "last_active_at": float(entry.get("last_active_at") or entry.get("opened_at") or 0.0),
            "last_input_tokens": int(entry["last_input_tokens"]) if type(entry.get("last_input_tokens")) is int else 0,
            "subcards": list(entry.get("subcards") or []),
            "entry": entry,
        })
    active.sort(key=lambda item: (item["last_active_at"], item["opened_at"], item["card"]))
    return active


def _codex_rpc_session() -> Callable[[str, dict], dict]:
    """A JSON-RPC client over one `codex app-server` stdio process (the official thread API, not Codex's own files)."""
    proc = subprocess.Popen([shutil.which("codex") or "codex", "app-server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    counter = {"id": 0}

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def answer(request_id: int) -> dict:
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(str(message["error"]))
                return message.get("result") or {}
        raise RuntimeError("codex app-server closed before answering")

    def call(method: str, params: dict) -> dict:
        counter["id"] += 1
        send({"jsonrpc": "2.0", "id": counter["id"], "method": method, "params": params})
        return answer(counter["id"])

    send({"jsonrpc": "2.0", "id": 0, "method": "initialize",
          "params": {"clientInfo": {"name": "uaos", "title": "UAOS", "version": "0"}}})
    answer(0)
    send({"jsonrpc": "2.0", "method": "initialized"})
    call.proc = proc
    return call


def _open_codex(project: Path, title: str, prompt: str, rpc: Callable[[str, dict], dict] | None) -> str:
    own = rpc is None
    if own:
        rpc = _codex_rpc_session()
    try:
        thread_id = rpc("thread/start", {"cwd": str(project)})["thread"]["id"]
        rpc("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]})
        # The name comes after the first turn: before it the thread has no rollout, so no sidebar row (U114 probe).
        rpc("thread/name/set", {"threadId": thread_id, "name": title})
        return thread_id
    finally:
        if own:
            rpc.proc.kill()


def _open_antigravity(project: Path, prompt: str, runner: Callable[..., Any]) -> tuple[str, int | None]:
    done = runner([shutil.which("agy") or "agy", "-p", prompt, "--output-format", "json"], cwd=str(project),
                  capture_output=True, text=True, encoding="utf-8", timeout=AGY_TIMEOUT_S)
    raw = done.stdout or ""
    try:
        envelope = json.loads(raw)
    except ValueError:
        match = re.search(r"\{.*\}", raw, re.S)
        envelope = json.loads(match.group(0)) if match else {}
    tokens = (envelope.get("usage") or {}).get("input_tokens")
    return str(envelope["conversation_id"]), tokens if type(tokens) is int and tokens >= 0 else None


def open_window(project: Path, card: str, tool: str, title: str, prompt: str, *,
                runner: Callable[..., Any] = subprocess.run, rpc: Callable[[str, dict], dict] | None = None,
                now: float | None = None, session_id: str | None = None) -> dict[str, Any]:
    project = Path(project)
    path = _record_path(project, card)
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    record = _load(path)
    if session_id is not None and tool != "claude":
        raise ValueError("--session-id applies to claude only")
    if session_id is not None:
        session_id = _claude_session_id(session_id)
    existing = record.get("tools", {}).get(tool)
    if existing and not existing.get("released_at"):  # U129: a released window is done, never reused
        return {**existing, "reused": True}
    state = read_presence(project, tool)["state"]
    if state in ("LIMITED", "ABSENT"):  # U113: nothing waits in a limited tool's thread
        return {"refused": state, "tool": tool, "card": card}
    name = window_title(card, title)
    extra: dict[str, Any] = {}
    if tool == "codex":
        window_id = _open_codex(project, name, prompt, rpc)
    elif tool == "claude":
        if session_id is None:
            return {"refused": "NO_VISIBLE_SESSION", "tool": tool, "card": card,
                    "message": NO_VISIBLE_SESSION.format(card=card)}
        holder = session_busy(project, session_id, card)
        if holder:
            return {"refused": "SESSION_BUSY", "tool": tool, "card": card, "held_by": holder,
                    "message": SESSION_BUSY.format(session=session_id, holder=holder)}
        window_id = session_id
    else:
        window_id, tokens = _open_antigravity(project, prompt, runner)
        if tokens is not None:  # U131: the opening turn's size, so the U127 resume cap can read it
            extra["last_input_tokens"] = tokens
    entry = {"id": window_id, "opened_at": time.time() if now is None else now, **extra}
    record = {"card": card, "title": name, "tools": {**record.get("tools", {}), tool: entry}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {**entry, "reused": False}


def acquire_topic_window(
    project: Path,
    card: str,
    tool: str,
    title: str,
    prompt: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
    rpc: Callable[[str, dict], dict] | None = None,
    now: float | None = None,
    session_id: str | None = None,
    max_active: int = MAX_ACTIVE_WINDOWS_PER_TOOL,
    token_cap: int = RESUME_MAX_INPUT,
    overflow_policy: str = "evict_lru",
) -> dict[str, Any]:
    """U279: Topic-grouped bounded window pool acquisition for Codex, Claude Code, and Antigravity.

    1. Normalizes `card` to its canonical `topic_key` (`U275-R8-L1` -> `U275`) so sub-tasks share one conversation.
    2. Reuses the existing `[topic_key]` window when active and under `token_cap` (`70,000` input tokens).
    3. Automatically rotates (`TOKEN_CAP_ROTATED`) when `last_input_tokens >= token_cap`.
    4. Enforces `max_active` (`MAX_ACTIVE_WINDOWS_PER_TOOL = 3`) per tool via `evict_lru` (auto-releases oldest idle
       topic window) or `share_least_loaded` (shares the active window with the lowest token load) to prevent window
       proliferation (대화창 남발 방지)."""
    project = Path(project)
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    ts = time.time() if now is None else now
    topic_key = normalize_topic_key(card, prompt) or card
    _record_path(project, topic_key)

    existing = window_entry(project, topic_key, tool)
    rotated_from: str | None = None
    if existing.get("id") and not existing.get("released_at"):
        tokens = existing.get("last_input_tokens")
        if type(tokens) is int and tokens >= token_cap:
            rotated_from = str(existing["id"])
            release_window(project, topic_key, tool, now=ts, reason="TOKEN_CAP_ROTATED")
        else:
            subcards = list(existing.get("subcards") or [])
            if card not in subcards:
                subcards.append(card)
            updated = record_window(
                project,
                topic_key,
                tool,
                str(existing["id"]),
                now=ts,
                **{k: v for k, v in existing.items() if k not in ("id", "opened_at", "last_active_at", "subcards", "topic_key")},
                subcards=subcards,
                topic_key=topic_key,
            )
            return {**updated, "reused": True, "topic_key": topic_key, "card": card}

    evicted_cards: list[str] = []
    active = active_topic_windows(project, tool)
    if max_active > 0 and len(active) >= max_active:
        if overflow_policy == "share_least_loaded":
            least = min(active, key=lambda item: (item["last_input_tokens"], item["last_active_at"]))
            subcards = list(least["subcards"])
            if card not in subcards:
                subcards.append(card)
            shared = record_window(
                project,
                topic_key,
                tool,
                least["id"],
                now=ts,
                topic_key=topic_key,
                shared_from=least["card"],
                subcards=subcards,
                last_input_tokens=least["last_input_tokens"],
            )
            return {**shared, "reused": True, "topic_key": topic_key, "card": card, "shared_from": least["card"]}
        # Default `evict_lru`: release oldest-active topic windows until active count is strictly below `max_active`.
        to_evict = len(active) - max_active + 1
        for victim in active[:to_evict]:
            release_window(project, victim["card"], tool, now=ts, reason="POOL_CAP_LRU_EVICTED")
            evicted_cards.append(victim["card"])

    opened = open_window(
        project,
        topic_key,
        tool,
        title,
        prompt,
        runner=runner,
        rpc=rpc,
        now=ts,
        session_id=session_id,
    )
    if "refused" in opened:
        return {**opened, "topic_key": topic_key, "requested_card": card}

    subcards = [topic_key] if card == topic_key else [topic_key, card]
    extra = {k: v for k, v in opened.items() if k not in ("id", "opened_at", "reused")}
    extra["topic_key"] = topic_key
    extra["subcards"] = subcards
    if rotated_from:
        extra["rotated_from"] = rotated_from
    if evicted_cards:
        extra["evicted_lru"] = evicted_cards
    saved = record_window(project, topic_key, tool, str(opened["id"]), now=ts, **extra)
    return {**saved, "reused": False, "topic_key": topic_key, "card": card}


def _claude_session_id(session_id: str) -> str:
    """U129: the caller's desktop session id, lower-cased; anything but a full UUID is refused."""
    session_id = (session_id or "").strip().lower()
    if not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"bad claude session id: {session_id!r}")
    return session_id


def session_busy(project: Path, session_id: str, card: str) -> str | None:
    """U129: the other card whose unreleased Claude window is this desktop session, else None."""
    session_id = _claude_session_id(session_id)
    topic = normalize_topic_key(card)
    for path in sorted((Path(project) / ".coord" / "windows").glob("*.json")):
        if path.stem in (card, topic):
            continue
        entry = _load(path).get("tools", {}).get("claude") or {}
        if entry.get("id") == session_id and not entry.get("released_at"):
            return path.stem
    return None


def release_window(project: Path, card: str, tool: str, *, now: float | None = None,
                   reason: str | None = None) -> dict[str, Any]:
    """U129: mark a card's window done so its Claude desktop session can take the next card."""
    entry = window_entry(project, card, tool)
    result = {"released": bool(entry), "card": card, "tool": tool}
    if entry and not entry.get("released_at"):
        extra = {k: v for k, v in entry.items() if k not in ("id", "opened_at")}
        if reason:
            extra["released_reason"] = reason
        record_window(project, card, tool, entry["id"], released_at=time.time() if now is None else now, **extra)
    return result


def route_window(project: Path, card: str, *, session_id: str | None = None) -> dict[str, Any]:
    """U129: the clickless route for a card: Codex (ACTIVE) -> idle visible Claude session -> Antigravity headless."""
    _record_path(project, card)
    topic_key = normalize_topic_key(card)
    if read_presence(project, "codex")["state"] == "ACTIVE":
        return {"route": "codex", "card": card, "topic_key": topic_key,
                "step": "conductor: open the card's Codex app-server thread (`uaos coord window --tool codex`)"}
    busy = None
    if session_id is not None:
        session_id = _claude_session_id(session_id)
        busy = session_busy(project, session_id, card)
        if busy is None:
            return {"route": "claude", "card": card, "topic_key": topic_key, "session_id": session_id,
                    "step": f"conductor: send the card manual to Claude desktop session {session_id} with send_message, "
                            f"then record it (`uaos coord window --tool claude --session-id {session_id}`)"}
    route = {"route": "antigravity", "card": card, "topic_key": topic_key,
             "step": "conductor: send the card to Antigravity headless (`agy -p`) and relay its result"}
    if busy:
        route["busy"] = busy
    return route
