"""Where pilot runs live.

`pilot run --work-dir` is free-form: `.coord/pilot` (AGENTS.md), `.work/pilot_P08` (P08) or `.coord` (the CLI
default). Readers that looked only at `.coord/pilot` missed real runs, so they look at every candidate.
"""

from __future__ import annotations

from pathlib import Path


def discover(project: Path) -> list[Path]:
    project = Path(project)
    candidates = [project / ".coord" / "pilot", project / ".coord"]
    work = project / ".work"
    if work.is_dir():
        children = sorted(child for child in work.iterdir() if child.is_dir())
        candidates += children
        # U210: work dirs also nest one level deeper, `.work/<a>/<b>` (e.g. .work/u210/run6).
        candidates += sorted(nested for child in children for nested in child.iterdir() if nested.is_dir())
    return [directory for directory in candidates if (directory / "runs").is_dir()]
