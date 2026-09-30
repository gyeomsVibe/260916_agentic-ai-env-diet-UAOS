```contract
work_id: U101-A1
worker: apply
goal: Write uaos_everywhere/hooks/absence_brief.py after two same-cause Ollama failures, listing what other tools changed since a time.
inputs:
- tests/test_u101_absence_brief.py sha256=9c954e7c13fa60ddb61430d9e41255300b9d3dcd386d2731676c12fe068c6a38
allow:
- uaos_everywhere/hooks/absence_brief.py
acceptance: python -m unittest tests.test_u101_absence_brief
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
apply_after: U101-L2
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

Write the file below exactly. Ollama failed twice with the same cause (U101-L1 and U101-L2: SYNTAX_ERROR in the constants section), so the judge dictates it under `apply_after: U101-L2` (U98-D).

===FILE: uaos_everywhere/hooks/absence_brief.py===
"""List what other tools changed in a project since a time, from git and files, at 0 model tokens (U101)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

# Commits Claude made carry this trailer; they are not news to Claude.
SELF_TRAILER = "Co-Authored-By: Claude"
# Folders where another tool leaves reports, memos and manuals.
FILE_FOLDERS = (".coord/tasks", ".coord/notes")
# git must answer fast inside a prompt hook.
GIT_TIMEOUT_S = 10


def _git(root: Path, *args: str) -> list[str]:
    """Run git in root and return its non-empty output lines, or nothing when git fails."""
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _epoch(stamp) -> float | None:
    """Parse an ISO time into epoch seconds, or None."""
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def absence_items(root: Path, since: float, self_tool: str = "claude") -> list[str]:
    """Commits, uncommitted edits, hand-written leases and report files that other tools made after `since`."""
    root = Path(root)
    items: list[str] = []
    for line in _git(root, "log", "--all", f"--since=@{int(since)}", "--invert-grep", f"--grep={SELF_TRAILER}",
                     "--format=%h %s"):
        items.append(f"commit {line}")
    for line in _git(root, "status", "--porcelain", "--untracked-files=no"):
        items.append(f"uncommitted {line.strip()}")
    presence = root / ".coord" / "presence"
    if presence.is_dir():
        for path in sorted(presence.glob("*.json")):
            tool = path.stem
            if "." in tool or tool == self_tool:
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
            items.append(f"lease {tool} {record.get('state')} observed {record.get('observed_at')} "
                         f"expires {record.get('expires_at')}")
    for folder in FILE_FOLDERS:
        base = root / folder
        if base.is_dir():
            for path in sorted(base.glob("*")):
                if path.is_file() and path.stat().st_mtime > since:
                    items.append(f"file {folder}/{path.name}")
    return items
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
