```contract
work_id: U114-W3
worker: apply
goal: A Claude window records the session id that claude --bg prints
inputs:
- v7_harness/coord/windows.py sha256=5501ea8b15e7a68a1baac54c15efcc87515c6aae06eb06cb2b91dea3d3227f29
- tests/test_u114_windows.py sha256=d41ccf6a079015956491ce2b81a6d53c39e7b95fd6b2d8927da3564b5949b5b4
allow:
- v7_harness/coord/windows.py
acceptance: python -m unittest tests.test_u114_windows tests.test_u113_desk_truth
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the block below exactly. (Live probe 2026-10-01: `claude --bg` ignores `--session-id`; the id is in its banner.)

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
def _open_claude(project: Path, title: str, prompt: str, runner: Callable[..., Any]) -> str:
    session_id = str(uuid.uuid4())  # chosen here, so the record never parses the CLI's banner
    runner([shutil.which("claude") or "claude", "--bg", "--name", title, "--session-id", session_id, prompt],
           cwd=str(project), capture_output=True, text=True, encoding="utf-8", timeout=CLAUDE_TIMEOUT_S)
    return session_id
=======
# `claude --bg` prints "backgrounded · <id> · <name>"; it ignores --session-id ("--bg manages the session id", probe).
CLAUDE_BANNER_RE = re.compile(r"backgrounded\s+\S+\s+([0-9a-f]{8,})")


def _open_claude(project: Path, title: str, prompt: str, runner: Callable[..., Any]) -> str:
    done = runner([shutil.which("claude") or "claude", "--bg", "--name", title, prompt],
                  cwd=str(project), capture_output=True, text=True, encoding="utf-8", timeout=CLAUDE_TIMEOUT_S)
    found = CLAUDE_BANNER_RE.search(f"{done.stdout or ''}\n{getattr(done, 'stderr', '') or ''}")
    if not found:
        raise RuntimeError(f"claude --bg printed no session id: {(done.stdout or '')[:200]!r}")
    return found.group(1)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
import time
import uuid
from pathlib import Path
=======
import time
from pathlib import Path
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
