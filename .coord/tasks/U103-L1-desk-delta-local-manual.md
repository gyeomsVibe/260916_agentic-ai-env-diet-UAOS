```contract
work_id: U103-L1
worker: local
goal: Add v7_harness/coord/desk_delta.py so every tool (claude, codex, antigravity) in any project learns what the other tools changed since it last looked.
inputs:
- tests/test_u103_desk_delta.py sha256=746447ff137babaaee3c1e9c7b5ce60f9163ff0f9e9bf50834fb4b7d7185bd75
allow:
- v7_harness/coord/desk_delta.py
context_allow:
- tests/test_u103_desk_delta.py
acceptance: python -m unittest tests.test_u103_desk_delta
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1200
remote_budget_tokens: 0
```

## Instructions for the worker

## Task (U103): new file `v7_harness/coord/desk_delta.py`

Create the new file `v7_harness/coord/desk_delta.py` with one ===FILE block. It tells one tool (claude, codex or
antigravity) what the other tools changed in a project folder since that tool last looked.

### Step 1: copy this file header exactly, in this order (do not move any line)

```
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
```

### Step 2: write these functions after the header, in this order

Each function has a one-line docstring. Separate top-level definitions by two blank lines.

`def canonical(tool: str) -> str:`
- `name = str(tool or "").strip().lower()`; return `ALIASES.get(name, name)`.

`def _git(root: Path, *args: str) -> list[str]:`
- Inside `try`: `result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S)`.
- On `(OSError, subprocess.SubprocessError)` return `[]`. If `result.returncode != 0` return `[]`.
- Return `[line for line in result.stdout.splitlines() if line.strip()]`.

`def _epoch(stamp) -> float | None:`
- If `stamp` is not a str return None. Inside try return `datetime.fromisoformat(stamp).timestamp()`; on `ValueError` return None.

`def _payload(path: Path) -> dict:`
- Inside try: `data = json.loads(path.read_text(encoding="utf-8", errors="replace"))`; on `(OSError, ValueError)` return `{}`.
- If `data` is not a dict return `{}`. `body = data.get("payload", data)`. Return `body` if it is a dict, else `{}`.

`def own_letter(path: Path, tool: str) -> bool:`
- `tool = canonical(tool)`; `name = path.name.lower()`.
- Return True when `name.startswith(f"{tool}_to_")`, or `tool in name.split("-")`, or `canonical(_payload(path).get("actor", "")) == tool`. Else False.

`def summary_of(path: Path) -> str:`
- `body = _payload(path)`.
- `text = str(body.get("summary") or body.get("verdict") or body.get("message") or path.name)`.
- Return `" ".join(text.split())[:SNIPPET]`.

`def plan_rows(path: Path) -> dict[str, str]:`
- `rows = {}`. Inside try over `path.read_text(encoding="utf-8", errors="replace").splitlines()`: when `line.startswith("| ")` and `line.count("|") >= 4`, set `cells = line.split("|")` and `rows[cells[1].strip()] = cells[2].strip()`. On `OSError` pass. Return `rows`.

`def absence_items(root: Path, since: float, tool: str) -> list[str]:`
- `root = Path(root)`; `tool = canonical(tool)`; `items: list[str] = []`.
- Commits: `args = ["log", "--all", "--no-merges", f"--since=@{int(since)}", "--format=%h %s"]`. If `tool in TRAILERS`, extend args with `["--invert-grep", f"--grep={TRAILERS[tool]}"]`. For each line of `_git(root, *args)` append `f"commit {line}"`.
- Uncommitted: for each line of `_git(root, "status", "--porcelain", "--untracked-files=no")` append `f"uncommitted {line.strip()}"`.
- Leases: `presence = root / ".coord" / "presence"`. If it is a directory, for each `path` in `sorted(presence.glob("*.json"))`: `other = path.stem`; skip when `other not in TOOLS or other == tool`. Read `record = json.loads(path.read_text(encoding="utf-8"))` in try; on `(OSError, ValueError)` continue. Skip when record is not a dict or `record.get("lease") is not True`. `observed = _epoch(record.get("observed_at"))`; skip when `observed is None or observed <= since`. Append `f"lease {other} {record.get('state')} observed {record.get('observed_at')}"`.
- Files: `tracked = set(_git(root, "ls-files", "--", *FILE_FOLDERS))`. For each `folder` in `FILE_FOLDERS`: `base = root / folder`; if it is a directory, for each `path` in `sorted(base.glob("*"))`: when `path.is_file()` and `path.stat().st_mtime > since` and `f"{folder}/{path.name}" not in tracked`, append `f"file {folder}/{path.name}"`.
- Return `items`.

`def cursor_path(project: Path, tool: str, session: str | None) -> Path:`
- `clean = re.sub(r"[^a-zA-Z0-9_-]", "_", str(session or "default")) or "default"`.
- Return `Path(project) / ".coord" / "presence" / f"desk_delta_{canonical(tool)}_{clean}.json"`.

`def delta_text(project: Path, tool: str, session: str | None = None, now: float | None = None) -> str:`
- `project = Path(project)`; `tool = canonical(tool)`; `now = time.time() if now is None else float(now)`.
- `path = cursor_path(project, tool, session)`. Read `cursor = json.loads(path.read_text(encoding="utf-8"))` in try; on `(OSError, ValueError)` set `cursor = {}`. If cursor is not a dict set `cursor = {}`.
- `since = float(cursor.get("since", now - FIRST_LOOK_S))`; `seen = cursor.get("plan", {})`; `items: list[str] = []`.
- Letters: `inbox = project / ".coord" / "mailbox" / "inbox"`. If it is a directory, for each `letter` in `sorted(inbox.glob("*.json"))`: skip when not a file, when `letter.stat().st_mtime <= since`, or when `own_letter(letter, tool)`. Append `f"letter {letter.stem}: {summary_of(letter)}"`.
- PLAN: `rows = plan_rows(project / ".coord" / "PLAN.md")`. For each `key, status` in `rows.items()`: when `key in seen and seen[key] != status`, append `f"PLAN {key}: {seen[key]} -> {status}"`.
- `items.extend(absence_items(project, since, tool))`.
- Write the cursor: `path.parent.mkdir(parents=True, exist_ok=True)`; `path.write_text(json.dumps({"since": now, "plan": rows}, ensure_ascii=False), encoding="utf-8")`.
- If `items` is empty return `""`.
- `lines = [f"DESK DELTA for {tool} ({len(items)} items since your last look): audit each before new work; the user must not have to paste it (U103)."]`.
- Append `f"- {item[:SNIPPET]}"` for each item in `items[:MAX_LINES]`. If `len(items) > MAX_LINES` append `f"- ... {len(items) - MAX_LINES} more not shown"`.
- Return `"\n".join(lines)`.

Do not change any other file.

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
