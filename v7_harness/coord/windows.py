"""U114: one process (card) gets one dedicated, named window in each tool: Codex app-server thread, Claude desktop
session (U129: recorded, never `claude --bg`), Antigravity conversation. The record `.coord/windows/<card>.json` maps the card to each tool's window id."""

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


def window_for(project: Path, card: str, tool: str) -> str | None:
    return _load(_record_path(project, card)).get("tools", {}).get(tool, {}).get("id")


def window_entry(project: Path, card: str, tool: str) -> dict[str, Any]:
    """U127: the card's window entry for one tool ({} when there is none)."""
    return dict(_load(_record_path(project, card)).get("tools", {}).get(tool) or {})


def record_window(project: Path, card: str, tool: str, window_id: str, *, now: float | None = None,
                  **extra: Any) -> dict[str, Any]:
    """U127: write one tool's window for a card and keep the other tools' windows (the U114 record format)."""
    path = _record_path(project, card)
    record = _load(path)
    entry = {"id": window_id, "opened_at": time.time() if now is None else now, **extra}
    old = record.get("tools", {}).get(tool) or {}
    if old.get("id") == window_id and "opened_at" in old:
        entry["opened_at"] = old["opened_at"]
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
    envelope = json.loads(done.stdout)
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


def _claude_session_id(session_id: str) -> str:
    """U129: the caller's desktop session id, lower-cased; anything but a full UUID is refused."""
    session_id = (session_id or "").strip().lower()
    if not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"bad claude session id: {session_id!r}")
    return session_id


def session_busy(project: Path, session_id: str, card: str) -> str | None:
    """U129: the other card whose unreleased Claude window is this desktop session, else None."""
    session_id = _claude_session_id(session_id)
    for path in sorted((Path(project) / ".coord" / "windows").glob("*.json")):
        if path.stem == card:
            continue
        entry = _load(path).get("tools", {}).get("claude") or {}
        if entry.get("id") == session_id and not entry.get("released_at"):
            return path.stem
    return None


def release_window(project: Path, card: str, tool: str, *, now: float | None = None) -> dict[str, Any]:
    """U129: mark a card's window done so its Claude desktop session can take the next card."""
    entry = window_entry(project, card, tool)
    result = {"released": bool(entry), "card": card, "tool": tool}
    if entry and not entry.get("released_at"):
        extra = {k: v for k, v in entry.items() if k not in ("id", "opened_at")}
        record_window(project, card, tool, entry["id"], released_at=time.time() if now is None else now, **extra)
    return result


def route_window(project: Path, card: str, *, session_id: str | None = None) -> dict[str, Any]:
    """U129: the clickless route for a card: Codex (ACTIVE) -> idle visible Claude session -> Antigravity headless."""
    _record_path(project, card)
    if read_presence(project, "codex")["state"] == "ACTIVE":
        return {"route": "codex", "card": card,
                "step": "conductor: open the card's Codex app-server thread (`uaos coord window --tool codex`)"}
    busy = None
    if session_id is not None:
        session_id = _claude_session_id(session_id)
        busy = session_busy(project, session_id, card)
        if busy is None:
            return {"route": "claude", "card": card, "session_id": session_id,
                    "step": f"conductor: send the card manual to Claude desktop session {session_id} with send_message, "
                            f"then record it (`uaos coord window --tool claude --session-id {session_id}`)"}
    route = {"route": "antigravity", "card": card,
             "step": "conductor: send the card to Antigravity headless (`agy -p`) and relay its result"}
    if busy:
        route["busy"] = busy
    return route
