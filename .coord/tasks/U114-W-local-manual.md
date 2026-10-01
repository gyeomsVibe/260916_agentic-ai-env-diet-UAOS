```contract
work_id: U114-W
worker: local
goal: Each card gets one named window per tool (Codex thread, Claude bg session, Antigravity conversation), recorded in .coord/windows
inputs:
- tests/test_u114_windows.py sha256=f6086649b9765644006112494b7cc15d6434f541f11996697a0ae6d4b650d5b3
- v7_harness/coord/presence.py sha256=cf977cbf00fa6ef78b16dec8738c8963441e8b6b6e5634b03938daecad3dc657
allow:
- v7_harness/coord/windows.py
acceptance: python -m unittest tests.test_u114_windows
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Create ONE new file, v7_harness/coord/windows.py, with a single ===FILE: v7_harness/coord/windows.py=== block.
The acceptance test tests/test_u114_windows.py is in your inputs: satisfy it exactly. Python 3.12, standard library only.

Module docstring (first lines of the file):
"""U114: one process (card) gets one dedicated, named window in each tool: Codex app-server thread, Claude background
session, Antigravity conversation. The record `.coord/windows/<card>.json` maps the card to each tool's window id."""

Imports: from __future__ import annotations; json, re, shutil, subprocess, time, uuid; from pathlib import Path;
from typing import Any, Callable; from v7_harness.coord.presence import read as read_presence.

Constants (each with a one-line comment saying why):
- CARD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")  # a card id is a file name; no separators or spaces
- TOOLS = ("codex", "claude", "antigravity")

Functions:

1. window_title(card: str, title: str) -> str: return f"[{card}] {title}".

2. _record_path(project: Path, card: str) -> Path: raise ValueError(f"bad card id: {card!r}") unless
   CARD_RE.fullmatch(card) and ".." not in card; return Path(project) / ".coord" / "windows" / f"{card}.json".

3. _load(path: Path) -> dict: return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}.

4. window_for(project: Path, card: str, tool: str) -> str | None:
   return _load(_record_path(project, card)).get("tools", {}).get(tool, {}).get("id").

5. _codex_rpc_session() -> Callable[[str, dict], dict]: start
   subprocess.Popen([shutil.which("codex") or "codex", "app-server"], stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
   text=True, encoding="utf-8"); send {"jsonrpc":"2.0","id":0,"method":"initialize","params":{"clientInfo":
   {"name":"uaos","title":"UAOS","version":"0"}}} and read lines until the one with "id" == 0; then send
   {"jsonrpc":"2.0","method":"initialized"}. Return a function call(method, params) that sends one request with the
   next integer id, reads stdout lines until the response with that id, raises RuntimeError(str(error)) if it has
   "error", and returns its "result" (or {}). Attach the Popen object as call.proc so the caller can kill it.

6. _open_codex(project: Path, title: str, prompt: str, rpc) -> str:
   own = rpc is None; if own: rpc = _codex_rpc_session().
   try: thread_id = rpc("thread/start", {"cwd": str(project)})["thread"]["id"];
   rpc("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]});
   rpc("thread/name/set", {"threadId": thread_id, "name": title}); return thread_id
   finally: if own: rpc.proc.kill().
   Comment above: the name is set after the first turn because a thread has no rollout (no sidebar row) before it.

7. _open_claude(project: Path, title: str, prompt: str, runner) -> str:
   session_id = str(uuid.uuid4());
   runner([shutil.which("claude") or "claude", "--bg", "--name", title, "--session-id", session_id, prompt],
   cwd=str(project), capture_output=True, text=True, encoding="utf-8", timeout=120); return session_id.

8. _open_antigravity(project: Path, prompt: str, runner) -> str:
   done = runner([shutil.which("agy") or "agy", "-p", prompt, "--output-format", "json"], cwd=str(project),
   capture_output=True, text=True, encoding="utf-8", timeout=900);
   return str(json.loads(done.stdout)["conversation_id"]).

9. open_window(project: Path, card: str, tool: str, title: str, prompt: str, *, runner=subprocess.run, rpc=None,
   now: float | None = None) -> dict[str, Any]:
   - path = _record_path(project, card) (this raises ValueError for a bad card before anything runs).
   - if tool not in TOOLS: raise ValueError(f"unknown tool: {tool}").
   - record = _load(path); existing = record.get("tools", {}).get(tool); if existing: return {**existing,
     "reused": True}.
   - state = read_presence(Path(project), tool)["state"]; if state in ("LIMITED", "ABSENT"): return
     {"refused": state, "tool": tool, "card": card}. Comment: U113, nothing waits in a limited tool's thread.
   - name = window_title(card, title); call _open_codex / _open_claude / _open_antigravity by tool to get window_id.
   - entry = {"id": window_id, "opened_at": time.time() if now is None else now};
     record = {"card": card, "title": name, "tools": {**record.get("tools", {}), tool: entry}};
     path.parent.mkdir(parents=True, exist_ok=True); write json.dumps(record, ensure_ascii=False, indent=2) to a
     sibling file path.with_suffix(".tmp") and then .replace(path).
   - return {**entry, "reused": False}.

Nothing else in the file. No prints.

## Output
- Reply with the ===FILE block only. No explanations. Do not claim success; the acceptance command decides.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
