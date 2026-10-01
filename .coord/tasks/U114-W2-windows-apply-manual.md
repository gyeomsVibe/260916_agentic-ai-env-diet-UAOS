```contract
work_id: U114-W2
worker: apply
goal: Each card gets one named window per tool (Codex thread, Claude bg session, Antigravity conversation), recorded in .coord/windows
inputs:
- tests/test_u114_windows.py sha256=f6086649b9765644006112494b7cc15d6434f541f11996697a0ae6d4b650d5b3
- v7_harness/coord/presence.py sha256=cf977cbf00fa6ef78b16dec8738c8963441e8b6b6e5634b03938daecad3dc657
allow:
- v7_harness/coord/windows.py
acceptance: python -m unittest tests.test_u114_windows tests.test_u113_desk_truth
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
apply_after: U114-W
```

## Instructions for the worker

Write the file below exactly. (Ollama run U114-W, judged REWORK: no presence import, `id` used before assignment in the
RPC call, the atomic write moved the record onto its .tmp file, annotations naming the test's `_Done` class, and string
matching on raw JSON lines. This is its corrected text.)

===FILE: v7_harness/coord/windows.py===
"""U114: one process (card) gets one dedicated, named window in each tool: Codex app-server thread, Claude background
session, Antigravity conversation. The record `.coord/windows/<card>.json` maps the card to each tool's window id."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.presence import read as read_presence

# A card id becomes a file name: no separators, spaces or "..", so a record never lands outside .coord/windows.
CARD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# The three tools that own windows; Ollama is a calculator and has none.
TOOLS = ("codex", "claude", "antigravity")
# Antigravity answers the opening prompt before it prints the conversation id; one long card turn fits in 15 minutes.
AGY_TIMEOUT_S = 900
# `claude --bg` returns as soon as the session is started (3 s measured on 2026-10-01).
CLAUDE_TIMEOUT_S = 120


def window_title(card: str, title: str) -> str:
    return f"[{card}] {title}"


def _record_path(project: Path, card: str) -> Path:
    if not CARD_RE.fullmatch(card or "") or ".." in card:
        raise ValueError(f"bad card id: {card!r}")
    return Path(project) / ".coord" / "windows" / f"{card}.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def window_for(project: Path, card: str, tool: str) -> str | None:
    return _load(_record_path(project, card)).get("tools", {}).get(tool, {}).get("id")


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


def _open_claude(project: Path, title: str, prompt: str, runner: Callable[..., Any]) -> str:
    session_id = str(uuid.uuid4())  # chosen here, so the record never parses the CLI's banner
    runner([shutil.which("claude") or "claude", "--bg", "--name", title, "--session-id", session_id, prompt],
           cwd=str(project), capture_output=True, text=True, encoding="utf-8", timeout=CLAUDE_TIMEOUT_S)
    return session_id


def _open_antigravity(project: Path, prompt: str, runner: Callable[..., Any]) -> str:
    done = runner([shutil.which("agy") or "agy", "-p", prompt, "--output-format", "json"], cwd=str(project),
                  capture_output=True, text=True, encoding="utf-8", timeout=AGY_TIMEOUT_S)
    return str(json.loads(done.stdout)["conversation_id"])


def open_window(project: Path, card: str, tool: str, title: str, prompt: str, *,
                runner: Callable[..., Any] = subprocess.run, rpc: Callable[[str, dict], dict] | None = None,
                now: float | None = None) -> dict[str, Any]:
    project = Path(project)
    path = _record_path(project, card)
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    record = _load(path)
    existing = record.get("tools", {}).get(tool)
    if existing:
        return {**existing, "reused": True}
    state = read_presence(project, tool)["state"]
    if state in ("LIMITED", "ABSENT"):  # U113: nothing waits in a limited tool's thread
        return {"refused": state, "tool": tool, "card": card}
    name = window_title(card, title)
    if tool == "codex":
        window_id = _open_codex(project, name, prompt, rpc)
    elif tool == "claude":
        window_id = _open_claude(project, name, prompt, runner)
    else:
        window_id = _open_antigravity(project, prompt, runner)
    entry = {"id": window_id, "opened_at": time.time() if now is None else now}
    record = {"card": card, "title": name, "tools": {**record.get("tools", {}), tool: entry}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {**entry, "reused": False}
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
