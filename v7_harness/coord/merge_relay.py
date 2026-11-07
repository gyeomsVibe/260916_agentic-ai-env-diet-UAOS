"""Merge Relay (U114): Automate PR merge notification to Claude Code.

Enables seamless non-stop handoff:
1. Detect open mergeable PRs from Claude.
2. When PR is merged, automatically notify Claude via coord deliver so Claude immediately starts the next card.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def get_open_prs(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return open PRs using gh CLI."""
    gh = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
    if not Path(gh).is_file():
        return []
    try:
        res = subprocess.run(
            [gh, "pr", "list", "--state", "open", "--json", "number,title,headRefName,url,mergeable"],
            capture_output=True, text=True, cwd=str(cwd) if cwd else None, timeout=15
        )
        if res.returncode == 0:
            return json.loads(res.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        pass
    return []


def notify_claude_merged(pr_number: int, branch: str, project_dir: Path | None = None) -> bool:
    """Send coord deliver to Claude notifying that PR has been merged into main."""
    from v7_harness.coord.deliver import deliver
    project = project_dir or Path.cwd()
    msg = (
        f"[병합 완료 통보] PR #{pr_number} ({branch}) 메인 병합 완료 확인.\n"
        f"ACTIONABLE_DELTA: 다음 단계 구현 계획대로 논스톱 진행 요망."
    )
    res = deliver(project, message=msg, actor="antigravity", target="claude")
    return res.delivered
