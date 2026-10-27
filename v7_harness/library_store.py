"""U250: Canonical Reference & Benchmark Library Store for UAOS-RSI.

Enforces the global rule that all GitHub sample and benchmarking reference
repositories used by UAOS-RSI (Codex, Claude Code, Antigravity) are uniformly
stored under:
  D:\\D_Workspace_NB\\-agentic-ai-workspace\\260916_agentic-ai-env-diet\\.work\\library\\<repo>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def is_symlink_or_junction(path: Path) -> bool:
    """True if path is a POSIX symlink, Windows junction, or reparse point."""
    import os
    try:
        if path.is_symlink():
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        if hasattr(os.path, "isjunction") and os.path.isjunction(path):
            return True
        st = path.lstat()
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs and (attrs & 0x0400):
            return True
    except OSError:
        return True
    return False


CANONICAL_LIBRARY_PATH_STR = (
    r"D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library"
)
CANONICAL_LIBRARY_ROOT = Path(CANONICAL_LIBRARY_PATH_STR)

_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_GIT_REF_RE = re.compile(r"^refs/[A-Za-z0-9._/-]+$")
_HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
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


def _is_safe_git_ref(git_dir: Path, ref_rel: str) -> Path | None:
    """Validate that a symbolic git ref stays strictly under `git_dir/refs/` with no traversal or symlinks."""
    if not ref_rel or ".." in ref_rel or "\\" in ref_rel or ":" in ref_rel or ref_rel.startswith("/"):
        return None
    if not _GIT_REF_RE.match(ref_rel):
        return None
    git_root = git_dir.resolve()
    candidate = git_dir / ref_rel
    try:
        cur = git_dir
        for part in Path(ref_rel).parts:
            cur = cur / part
            if cur.is_symlink():
                return None
        resolved = candidate.resolve()
        if not resolved.is_relative_to(git_root / "refs"):
            return None
        return resolved
    except OSError:
        return None


def _read_git_head_and_origin(git_dir: Path) -> tuple[str, str, bool]:
    """Read HEAD commit SHA (9 chars), remote.origin.url, and ref safety flag from `.git/` without subprocess."""
    commit_sha = "UNKNOWN"
    ref_safe = True
    try:
        head_file = git_dir / "HEAD"
        if head_file.is_symlink():
            return "UNKNOWN", "", False
        head_raw = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if head_raw.startswith("ref:"):
            ref_rel = head_raw.split(":", 1)[1].strip()
            safe_ref_file = _is_safe_git_ref(git_dir, ref_rel)
            if safe_ref_file is None:
                ref_safe = False
                commit_sha = "INVALID_REF"
            elif safe_ref_file.is_file():
                raw_sha = safe_ref_file.read_text(encoding="utf-8", errors="replace").strip()
                if _HEX_SHA_RE.match(raw_sha):
                    commit_sha = raw_sha[:9]
                else:
                    ref_safe = False
                    commit_sha = "INVALID_SHA"
            else:
                packed = git_dir / "packed-refs"
                if packed.is_file() and not packed.is_symlink():
                    for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                        if not line.startswith("#") and line.endswith(f" {ref_rel}"):
                            cand_sha = line.split()[0].strip()
                            if _HEX_SHA_RE.match(cand_sha):
                                commit_sha = cand_sha[:9]
                            break
        elif _HEX_SHA_RE.match(head_raw):
            commit_sha = head_raw[:9]
        else:
            ref_safe = False
    except OSError:
        commit_sha = "UNKNOWN"
        ref_safe = False

    origin_url = ""
    try:
        cfg_file = git_dir / "config"
        if cfg_file.is_file() and not cfg_file.is_symlink():
            in_origin = False
            for raw_line in cfg_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if line.startswith("[") and line.endswith("]"):
                    in_origin = line.lower() == '[remote "origin"]'
                elif in_origin and line.lower().startswith("url"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        origin_url = parts[1].strip()
                        break
    except OSError:
        origin_url = ""
    if origin_url.endswith(".git"):
        origin_url = origin_url[:-4]
    return commit_sha, origin_url, ref_safe


def inspect_library_repo(repo_dir: Path) -> dict[str, Any]:
    """Inspect a cloned reference repository inside `.work/library/<repo>` without executing any code or subprocess."""
    repo_path = Path(repo_dir).resolve()
    if not repo_path.is_dir():
        return {
            "ok": False,
            "error": "REPO_DIR_MISSING",
            "path": str(repo_path),
        }
    git_dir = repo_path / ".git"
    if not git_dir.exists() or is_symlink_or_junction(git_dir) or git_dir.resolve() != (repo_path.resolve() / ".git"):
        return {
            "ok": False,
            "error": "NOT_A_GIT_REPO",
            "path": str(repo_path),
        }

    commit_sha, origin_url, ref_safe = _read_git_head_and_origin(git_dir)
    if not ref_safe:
        return {
            "ok": False,
            "error": "UNSAFE_GIT_HEAD_REF",
            "name": repo_path.name,
            "path": str(repo_path),
            "origin_url": origin_url,
            "commit_sha": "UNKNOWN",
            "file_count": 0,
            "total_bytes": 0,
            "read_only_isolated": False,
        }

    file_count = 0
    total_bytes = 0
    symlink_escaped = False
    for item in repo_path.rglob("*"):
        if ".git" in item.parts:
            continue
        if is_symlink_or_junction(item):
            symlink_escaped = True
            continue
        try:
            if not item.resolve().is_relative_to(repo_path.resolve()):
                symlink_escaped = True
                continue
        except OSError:
            symlink_escaped = True
            continue
        if item.is_symlink():
            try:
                if not item.resolve().is_relative_to(repo_path):
                    symlink_escaped = True
            except OSError:
                symlink_escaped = True
            continue
        if item.is_file():
            file_count += 1
            try:
                total_bytes += item.stat().st_size
            except OSError:
                pass

    return {
        "ok": not symlink_escaped,
        "name": repo_path.name,
        "path": str(repo_path),
        "origin_url": origin_url,
        "commit_sha": commit_sha,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "read_only_isolated": not symlink_escaped,
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
    new_row = (
        f"| `{clean_folder}/` | {source_cell} | {license_id} | "
        f"{commit_sha} | {file_count} |"
    )

    header_block = (
        "# UAOS-RSI 참조·벤치마킹 자료실 (`.work/library`)\n\n"
        "> **전역 규칙(U250)**: 외부 공개 저장소 및 벤치마킹 샘플은 모두 본 폴더(`.work/library/<저장소명>`)에\n"
        "> 읽기 전용(Read-Only)으로 격리 보관하며, 내부에서 설치·빌드·스크립트 실행을 절대 금지합니다.\n\n"
        "| 폴더 | 원본 URL | 라이선스 | 커밋 SHA | 파일 수 |\n"
        "|---|---|---|---|---|\n"
    )

    if not readme_path.is_file():
        readme_path.write_text(header_block + new_row + "\n", encoding="utf-8")
        return readme_path

    lines = readme_path.read_text(encoding="utf-8").splitlines()
    marker = f"| `{clean_folder}/` |"
    updated = False
    out_lines: list[str] = []
    for line in lines:
        if line.strip().startswith(marker):
            out_lines.append(new_row)
            updated = True
        else:
            out_lines.append(line)

    if not updated:
        out_lines.append(new_row)

    readme_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return readme_path
