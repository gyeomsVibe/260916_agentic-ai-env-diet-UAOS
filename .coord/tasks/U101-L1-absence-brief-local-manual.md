```contract
work_id: U101-L1
worker: local
goal: Add uaos_everywhere/hooks/absence_brief.py that lists commits, uncommitted edits, leases and report files other tools made since a time.
inputs:
- tests/test_u101_absence_brief.py sha256=9c954e7c13fa60ddb61430d9e41255300b9d3dcd386d2731676c12fe068c6a38
allow:
- uaos_everywhere/hooks/absence_brief.py
context_allow:
- tests/test_u101_absence_brief.py
acceptance: python -m unittest tests.test_u101_absence_brief
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

## Task (U101): new file `uaos_everywhere/hooks/absence_brief.py`

Create the new file `uaos_everywhere/hooks/absence_brief.py` with one ===FILE block. It lists what other tools changed in a project folder since a time, read from git and files. Use only the standard library: `json`, `subprocess`, `datetime` (`datetime`), `pathlib.Path`. Start with a one-line module docstring, then `from __future__ import annotations`.

Constants, each with its comment on its own line above it:

```
# Commits Claude made carry this trailer; they are not news to Claude.
SELF_TRAILER = "Co-Authored-By: Claude"
# Folders where another tool leaves reports, memos and manuals.
FILE_FOLDERS = (".coord/tasks", ".coord/notes")
# git must answer fast inside a prompt hook.
GIT_TIMEOUT_S = 10
```

Function `_git(root: Path, *args: str) -> list[str]`:
- Run `subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S)` inside `try`.
- On `(OSError, subprocess.SubprocessError)` return `[]`. If `returncode != 0` return `[]`.
- Return `[line for line in result.stdout.splitlines() if line.strip()]`.

Function `_epoch(stamp) -> float | None`:
- If `stamp` is not a str, return None. Return `datetime.fromisoformat(stamp).timestamp()` inside try; on `ValueError` return None.

Function `absence_items(root: Path, since: float, self_tool: str = "claude") -> list[str]`:
- `root = Path(root)` and `items: list[str] = []`.
- Commits: for each line of `_git(root, "log", "--all", f"--since=@{int(since)}", "--invert-grep", f"--grep={SELF_TRAILER}", "--format=%h %s")` append `f"commit {line}"`.
- Uncommitted edits: for each line of `_git(root, "status", "--porcelain", "--untracked-files=no")` append `f"uncommitted {line.strip()}"`.
- Leases: let `presence = root / ".coord" / "presence"`. If it is a directory, for each `path` in `sorted(presence.glob("*.json"))`:
  - `tool = path.stem`. Skip when `"." in tool` (watch files) or `tool == self_tool`.
  - Read `record = json.loads(path.read_text(encoding="utf-8"))` inside try; on `(OSError, ValueError)` continue. Skip when `record` is not a dict or `record.get("lease") is not True`.
  - `observed = _epoch(record.get("observed_at"))`. Skip when `observed is None or observed <= since`.
  - Append `f"lease {tool} {record.get('state')} observed {record.get('observed_at')} expires {record.get('expires_at')}"`.
- Files: for each `folder` in `FILE_FOLDERS`, let `base = root / folder`. If it is a directory, for each `path` in `sorted(base.glob("*"))`: when `path.is_file()` and `path.stat().st_mtime > since`, append `f"file {folder}/{path.name}"`.
- Return `items`.

Give each function a one-line docstring. Separate top-level definitions by two blank lines. Do not change any other file.

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
