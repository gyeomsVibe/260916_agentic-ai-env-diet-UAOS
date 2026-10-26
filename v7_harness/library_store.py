"""U250: Canonical Reference & Benchmark Library Store for UAOS-RSI.

Enforces the global rule that all GitHub sample and benchmarking reference
repositories used by UAOS-RSI (Codex, Claude Code, Antigravity) are uniformly
stored under:
  D:\\D_Workspace_NB\\-agentic-ai-workspace\\260916_agentic-ai-env-diet\\.work\\library\\<repo>

Invariants enforced:
1. Single canonical root (`.work/library/<repo>`), rejecting path traversal or
   placement outside `.work/library`.
2. Read-only untrusted isolation: reference code is never installed, built, or
   executed (`npm install`, `cargo build`, script execution forbidden).
3. Automatic inventory registration in `.work/library/README.md` (folder,
   source URL, license, commit SHA, file count).
4. Excluded from parent repository commits via `.gitignore` (`.work/`).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

CANONICAL_LIBRARY_PATH_STR = (
    r"D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library"
)
CANONICAL_LIBRARY_ROOT = Path(CANONICAL_LIBRARY_PATH_STR)

_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_GITHUB_URL_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)?(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


def extract_repo_name(repo_slug_or_url: str) -> str:
    """Extract a safe repository folder name from a GitHub URL, owner/repo slug, or repo name."""
    raw = (repo_slug_or_url or "").strip()
    if not raw or ".." in raw:
        raise ValueError(f"INVALID_LIBRARY_REPO: {repo_slug_or_url!r}")
    match = _GITHUB_URL_RE.match(raw)
    if match:
        repo = match.group("repo")
    else:
        repo = raw.strip("/\\")
    if not _REPO_NAME_RE.match(repo) or repo in {".", "..", "_analysis", "_tmp"}:
        raise ValueError(f"INVALID_LIBRARY_REPO_NAME: {repo!r}")
    return repo


def resolve_library_repo_path(
    repo_slug_or_url: str,
    library_root: Path | None = None,
) -> Path:
    """Resolve the canonical `.work/library/<repo>` destination path."""
    root = Path(library_root) if library_root is not None else CANONICAL_LIBRARY_ROOT
    repo_name = extract_repo_name(repo_slug_or_url)
    resolved_root = root.resolve()
    target = (resolved_root / repo_name).resolve()
    if target.parent != resolved_root:
        raise ValueError(f"LIBRARY_PATH_ESCAPE: {target}")
    return target


def inspect_library_repo(repo_dir: Path) -> dict[str, Any]:
    """Inspect a cloned reference repository inside `.work/library/<repo>` without executing any code."""
    repo_path = Path(repo_dir).resolve()
    if not repo_path.is_dir():
        return {
            "ok": False,
            "error": "REPO_DIR_MISSING",
            "path": str(repo_path),
        }
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return {
            "ok": False,
            "error": "NOT_A_GIT_REPO",
            "path": str(repo_path),
        }

    head_proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--short=9", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit_sha = head_proc.stdout.strip() if head_proc.returncode == 0 else "UNKNOWN"

    remote_proc = subprocess.run(
        ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
        check=False,
    )
    origin_url = remote_proc.stdout.strip() if remote_proc.returncode == 0 else ""
    if origin_url.endswith(".git"):
        origin_url = origin_url[:-4]

    file_count = 0
    total_bytes = 0
    for item in repo_path.rglob("*"):
        if ".git" in item.parts:
            continue
        if item.is_file():
            file_count += 1
            try:
                total_bytes += item.stat().st_size
            except OSError:
                pass

    return {
        "ok": True,
        "name": repo_path.name,
        "path": str(repo_path),
        "origin_url": origin_url,
        "commit_sha": commit_sha,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "read_only_isolated": True,
    }


def register_library_entry(
    library_root: Path,
    folder_name: str,
    source_url: str,
    license_id: str,
    commit_sha: str,
    file_count: int,
    description: str = "",
) -> Path:
    """Idempotently register or update a benchmark/sample project row in `.work/library/README.md`."""
    root = Path(library_root)
    root.mkdir(parents=True, exist_ok=True)
    readme_path = root / "README.md"

    clean_folder = extract_repo_name(folder_name)
    source_cell = f"{source_url} ({description})" if description else source_url
    new_row = f"| `{clean_folder}/` | {source_cell} | {license_id} | {commit_sha} | {int(file_count)} |"

    if not readme_path.exists():
        content = (
            "# 자료실 (reference library)\n\n"
            "외부 저장소를 그대로 받아 둔 곳입니다. 폴더 하나가 독립된 git 프로젝트이며, "
            "이 프로젝트(.gitignore의 `.work/`)의 커밋에는 들어가지 않습니다.\n\n"
            "| 폴더 | 원본 | 라이선스 | 받은 커밋 | 파일 수 |\n"
            "|---|---|---|---|---|\n"
            f"{new_row}\n"
        )
        readme_path.write_text(content, encoding="utf-8")
        return readme_path

    lines = readme_path.read_text(encoding="utf-8").splitlines()
    row_prefix = f"| `{clean_folder}/` |"
    replaced = False
    updated_lines: list[str] = []
    last_table_idx = -1

    for idx, line in enumerate(lines):
        if line.strip().startswith(row_prefix):
            updated_lines.append(new_row)
            replaced = True
        else:
            updated_lines.append(line)
        if line.strip().startswith("|"):
            last_table_idx = len(updated_lines) - 1

    if not replaced:
        if last_table_idx >= 0:
            updated_lines.insert(last_table_idx + 1, new_row)
        else:
            updated_lines.extend(
                [
                    "",
                    "| 폴더 | 원본 | 라이선스 | 받은 커밋 | 파일 수 |",
                    "|---|---|---|---|---|",
                    new_row,
                ]
            )

    readme_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return readme_path
