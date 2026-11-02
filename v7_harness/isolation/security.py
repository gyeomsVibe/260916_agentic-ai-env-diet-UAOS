"""Path security, canonicalization, and boundary verification."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import stat
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from v7_harness.isolation.errors import (
    AlternateDataStreamError,
    CaseAliasError,
    ExternalWriteDetectedError,
    PathOutsideRootError,
    PathSecurityError,
    PathTraversalError,
    ReparsePointError,
    ScopeExpansionError,
    UncPathError,
    WatchScanUnavailableError,
)

# NTFS Reparse Point attribute flag
REPARSE_POINT_ATTR = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_symlink_or_reparse(path: Path) -> bool:
    """Return True if path is a symlink, junction, or reparse point."""
    try:
        if path.is_symlink():
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        st = path.lstat()
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & REPARSE_POINT_ATTR:
            return True
    except (OSError, ValueError):
        pass
    return False


def assert_no_reparse_or_symlink(path: Path, root: Path | None = None) -> None:
    """Walk up from path to root, ensuring no symlink or reparse point exists."""
    curr = path
    resolved_root = root.resolve() if root is not None else None

    while True:
        if curr.exists() or curr.is_symlink():
            if is_symlink_or_reparse(curr):
                raise ReparsePointError(f"Reparse point or symlink detected at: {curr}")

        if resolved_root is not None and curr.resolve() == resolved_root:
            break
        parent = curr.parent
        if parent == curr:
            break
        curr = parent


def validate_safe_relative_path(rel_path: str | Path) -> str:
    """Validate that relative path is safe from traversal, UNC, and ADS."""
    raw = str(rel_path).strip()
    if not raw:
        raise PathTraversalError("Empty relative path")

    if "\0" in raw:
        raise PathTraversalError("Null byte in path")

    # Reject UNC and network prefixes
    if raw.startswith(("\\\\", "//", "\\??\\", "\\\\?\\")):
        raise UncPathError(f"UNC or device path rejected: {raw}")

    # Reject absolute paths (POSIX leading slash or Windows leading backslash)
    if raw.startswith(("/", "\\")):
        raise PathOutsideRootError(f"Absolute path rejected: {raw}")

    # Reject NTFS Alternate Data Stream or relative drive letters (e.g. 'C:file')
    if ":" in raw:
        raise AlternateDataStreamError(f"Colon or Alternate Data Stream detected in path: {raw}")

    # Reject 8.3 DOS/Windows short filename alias (e.g. PROGRA~1)
    if "~" in raw:
        raise PathSecurityError(f"8.3 short filename alias rejected: {raw}", error_class="DOS_8_3_ALIAS_FORBIDDEN")

    # Normalize to forward slashes for checking
    posix_str = raw.replace("\\", "/")
    parts = PurePosixPath(posix_str).parts

    for part in parts:
        if part in ("..", "."):
            raise PathTraversalError(f"Traversal component '{part}' in path: {raw}")
        if ":" in part:
            raise AlternateDataStreamError(f"Alternate Data Stream in component '{part}': {raw}")
        if "~" in part:
            raise PathSecurityError(f"8.3 alias in component '{part}': {raw}", error_class="DOS_8_3_ALIAS_FORBIDDEN")

    # Reassemble clean posix path
    clean = "/".join(parts)
    return clean


def validate_canonical_path_in_root(root: Path, rel_path: str | Path) -> Path:
    """Resolve and verify canonical path is strictly confined inside root."""
    safe_rel = validate_safe_relative_path(rel_path)
    canonical_root = root.resolve()

    assert_no_reparse_or_symlink(canonical_root)

    target = (canonical_root / safe_rel).resolve()

    try:
        target.relative_to(canonical_root)
    except ValueError:
        raise PathOutsideRootError(f"Target '{target}' escapes root '{canonical_root}'")

    # Double-check string containment (handles Windows case-preservation)
    try:
        common = os.path.commonpath([str(canonical_root), str(target)])
        if common != str(canonical_root):
            raise PathOutsideRootError(f"Target '{target}' outside canonical root '{canonical_root}'")
    except ValueError:
        raise PathOutsideRootError(f"Cross-drive escape detected between '{canonical_root}' and '{target}'")

    return target


def check_case_alias_set(paths: Sequence[str]) -> None:
    """Fail closed if multiple paths collide under case-folding."""
    seen: dict[str, str] = {}
    for p in paths:
        normalized = p.replace("\\", "/").strip().lower()
        if normalized in seen:
            raise CaseAliasError(f"Case alias collision between '{seen[normalized]}' and '{p}'")
        seen[normalized] = p


def check_case_match_on_disk(root: Path, rel_path: str) -> None:
    """Fail closed if relative path casing does not strictly match on-disk casing."""
    safe_rel = validate_safe_relative_path(rel_path)
    parts = PurePosixPath(safe_rel).parts
    curr = root.resolve()

    for part in parts:
        if not curr.exists() or not curr.is_dir():
            break
        try:
            entries = os.listdir(curr)
        except OSError:
            break

        matches = [e for e in entries if e.lower() == part.lower()]
        if matches:
            if part not in matches:
                raise CaseAliasError(
                    f"Case alias detected: path component '{part}' mismatches disk casing '{matches[0]}'"
                )
        curr = curr / part


def check_scope_confinement(rel_path: str, allowed_scopes: Sequence[str | Path] | None) -> None:
    """Fail closed if relative path is outside allowed scopes."""
    if allowed_scopes is None:
        return

    safe_rel = validate_safe_relative_path(rel_path)

    for scope in allowed_scopes:
        scope_str = str(scope).replace("\\", "/").rstrip("/")
        if not scope_str or scope_str == "*":
            return
        if safe_rel == scope_str or safe_rel.startswith(scope_str + "/"):
            return
        if fnmatch.fnmatch(safe_rel, scope_str):
            return

    raise ScopeExpansionError(f"Path '{rel_path}' is outside allowed scopes: {list(allowed_scopes)}")


DEFAULT_WATCH_EXCLUDES = frozenset(
    {
        "appdata",
        "appdata/**",
        ".codex",
        ".codex/**",
        ".cache",
        ".cache/**",
        ".claude",
        ".claude/**",
        ".claude.json",
        "claude",
        "claude/**",
        ".gemini/antigravity/brain",
        ".gemini/antigravity/brain/**",
        "????????-????-????-????-????????????.tmp",
        "unleash-repo-schema-v1-codeium-language-server.json",
        # B46: Visual Studio background-download logs and system temp files at the TEMP root.
        "dd_backgrounddownload_*.log",
        "tmp[0-9a-f][0-9a-f][0-9a-f][0-9a-f].tmp",
        # Windows flushes the user registry hive log (ntuser.dat.LOG1/2) at the home root on its own schedule. A 2-min
        # lane run hit it (2026-09-23, EXTERNAL_WRITE on ntuser.dat.LOG2 with no worker write). The hive is written
        # lazily by the OS, so this file never was a reliable signal of a worker's registry change.
        "ntuser.dat.log*",
        # U300: transient %TEMP% test/worker files from real EXTERNAL_WRITE receipts
        # (U134-F2 uaos_test_olla_usage_*, U301-L2 tmp????????, R0CLOSE2/3 codex-clipboard-*.png, U23_FIX_SENTINEL2 cv_debug.log)
        "uaos_test_olla_usage_*.jsonl",
        "uaos_test_olla_usage_*.lock",
        "tmp????????",
        "tmp????????/**",
        "codex-clipboard-*.png",
        "cv_debug.log",
        "**/node_modules",
        "**/node_modules/**",
        "**/.venv",
        "**/.venv/**",
        "**/venv",
        "**/venv/**",
    }
)
DEFAULT_WATCH_REINCLUDES = frozenset(
    {
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".claude/claude.md",
        ".claude/hooks",
        ".claude/agents",
        ".claude/skills",
        ".claude/commands",
        ".claude/rules",
        ".codex/config.toml",
        ".codex/agents.md",
        ".codex/rules",
        ".codex/skills",
    }
)

# B39: Heavy subdirectories excluded from re-included directories to prevent watch budget exhaustion
HEAVY_REINCLUDE_SUBDIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".cache",
    }
)

# Backward-compatible alias
PROTECTED_WATCH_FILES = DEFAULT_WATCH_REINCLUDES


def _case_insensitive_existing(root: Path, rel_path: str) -> list[Path]:
    """On-disk paths matching rel_path per component ignoring case (reinclude entries are lower-case,
    so `root / entry` misses `.claude/CLAUDE.md` on case-sensitive filesystems)."""
    current = [root]
    for part in rel_path.split("/"):
        folded = part.casefold()
        found: list[Path] = []
        for base in current:
            try:
                names = os.listdir(base)
            except OSError:
                continue
            found.extend(base / name for name in sorted(names) if name.casefold() == folded)
        current = found
    return current


def is_protected_watch_path(rel_path: str) -> bool:
    """Return True if rel_path matches a re-include entry or is under one, excluding heavy subdirs."""
    parts = [p.casefold() for p in rel_path.replace("\\", "/").strip("/").split("/") if p]
    if not parts:
        return False
    normalized = "/".join(parts)
    for protected in DEFAULT_WATCH_REINCLUDES:
        prot_parts = [p.casefold() for p in protected.replace("\\", "/").strip("/").split("/") if p]
        k = len(prot_parts)
        if len(parts) >= k and parts[:k] == prot_parts:
            if any(part in HEAVY_REINCLUDE_SUBDIRS for part in parts[k + 1 :]):
                return False
            return True
    return False


def is_protected_watch_dir_ancestor(rel_dir: str) -> bool:
    """Return True if rel_dir is an ancestor directory of any re-include entry, excluding heavy subdirs."""
    parts = [p.casefold() for p in rel_dir.replace("\\", "/").strip("/").split("/")]
    if any(part in HEAVY_REINCLUDE_SUBDIRS for part in parts):
        return False
    normalized = "/".join(parts)
    for protected in DEFAULT_WATCH_REINCLUDES:
        if protected.startswith(normalized + "/") or normalized == protected:
            return True
    return False


EMPTY_CONTENT_FINGERPRINT = hashlib.sha256(b"").hexdigest()


@lru_cache(maxsize=32)
def _watch_exclude_regex(patterns: frozenset[str]) -> re.Pattern[str]:
    expressions = [fnmatch.translate(pattern) for pattern in sorted(patterns)]
    return re.compile("(?:" + "|".join(expressions) + ")")


# App-managed sync caches inside re-included dirs: rewritten by the Claude app on its own schedule.
DEFAULT_REINCLUDE_NOISE = frozenset({".claude/skills/synced"})


def is_reinclude_noise_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/").casefold()
    return any(normalized == noise or normalized.startswith(noise + "/") for noise in DEFAULT_REINCLUDE_NOISE)


def is_heavy_reinclude_path(rel_path: str) -> bool:
    """Return True if rel_path is inside a heavy subdirectory under a re-included tree."""
    parts = [p.casefold() for p in rel_path.replace("\\", "/").strip("/").split("/") if p]
    if not parts:
        return False
    if is_reinclude_noise_path(rel_path):
        return False
    for protected in DEFAULT_WATCH_REINCLUDES:
        prot_parts = [p.casefold() for p in protected.replace("\\", "/").strip("/").split("/") if p]
        k = len(prot_parts)
        if len(parts) >= k and parts[:k] == prot_parts:
            if any(part in HEAVY_REINCLUDE_SUBDIRS for part in parts[k + 1 :]):
                return True
    return False


def is_under_reinclude_tree(rel_path: str) -> bool:
    """Return True if rel_path is inside a re-included directory (or is a re-include entry)."""
    parts = [p.casefold() for p in rel_path.replace("\\", "/").strip("/").split("/") if p]
    if not parts:
        return False
    for protected in DEFAULT_WATCH_REINCLUDES:
        prot_parts = [p.casefold() for p in protected.replace("\\", "/").strip("/").split("/") if p]
        k = len(prot_parts)
        if len(parts) >= k and parts[:k] == prot_parts:
            return True
    return False


def _watch_path_excluded(rel_path: str, patterns: frozenset[str]) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/").casefold()
    if is_reinclude_noise_path(normalized):
        return True
    if is_protected_watch_path(normalized):
        return False
    return _watch_exclude_regex(patterns).fullmatch(normalized) is not None


def _bounded_content_fingerprint(path: Path, size: int) -> str:
    """Hash complete content; the caller enforces a bounded per-root byte budget."""
    if size == 0:
        return EMPTY_CONTENT_FINGERPRINT
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class WatchScanResult:
    root_exists: bool
    files: dict[str, tuple[int, int, int, str]]


def _scan_watch_root(
    root: Path,
    *,
    excludes: frozenset[str],
    recursive: bool,
    max_files: int,
    max_fingerprint_bytes: int,
) -> WatchScanResult:
    """Collect bounded stat metadata without reading file contents."""
    result: dict[str, tuple[int, int, int, str]] = {}
    fingerprint_bytes = 0
    if is_symlink_or_reparse(root):
        raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: watch root became reparse or symlink {root}")
    if not root.exists():
        return WatchScanResult(root_exists=False, files=result)

    def record(path: Path, *, allow_link: bool = False) -> None:
        nonlocal fingerprint_bytes
        rel = str(path.relative_to(root)).replace("\\", "/")
        if is_reinclude_noise_path(rel):
            return

        is_heavy = is_heavy_reinclude_path(rel)
        if not is_heavy and _watch_path_excluded(rel, excludes):
            return

        if is_symlink_or_reparse(path):
            if not allow_link:
                raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: reparse or symlink {path}")
            # Shallow scans never traverse links; record the link's own identity so that
            # creation, removal, or retargeting is still detected as an external change.
            if len(result) >= max_files:
                raise PathSecurityError(
                    f"Watch root file budget exceeded ({max_files}): {root}",
                    error_class="WATCH_ROOT_BUDGET_EXCEEDED",
                )
            try:
                link_details = path.lstat()
            except (OSError, ValueError) as exc:
                raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: lstat {path}: {exc}") from exc
            try:
                target = os.readlink(path)
            except (OSError, ValueError):
                target = "UNREADABLE"
            result[rel] = (0, link_details.st_mtime_ns, link_details.st_ctime_ns, f"LINK:{target}")
            return
        if len(result) >= max_files:
            raise PathSecurityError(
                f"Watch root file budget exceeded ({max_files}): {root}",
                error_class="WATCH_ROOT_BUDGET_EXCEEDED",
            )
        try:
            details = path.stat()
        except (OSError, ValueError) as exc:
            raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: stat {path}: {exc}") from exc

        if is_heavy:
            # B39: Heavy subdirectories in re-include trees: record metadata only, no content hash, no fingerprint budget consumption.
            result[rel] = (
                details.st_size,
                details.st_mtime_ns,
                details.st_ctime_ns,
                f"META:{details.st_size}:{details.st_mtime_ns}",
            )
            return

        planned_bytes = details.st_size
        if fingerprint_bytes + planned_bytes > max_fingerprint_bytes:
            raise PathSecurityError(
                f"Watch root fingerprint budget exceeded ({max_fingerprint_bytes} bytes): {root}",
                error_class="WATCH_FINGERPRINT_BUDGET_EXCEEDED",
            )
        try:
            fingerprint = _bounded_content_fingerprint(path, details.st_size)
            verified = details if details.st_size == 0 else path.stat()
        except PermissionError:
            # Exclusively locked by another process (sharing violation / access denied).
            # Keep metadata-only evidence for this file instead of failing the whole root;
            # any metadata change on it is still reported as an UNKNOWN external write.
            result[rel] = (details.st_size, details.st_mtime_ns, details.st_ctime_ns, "LOCKED")
            return
        except (OSError, ValueError) as exc:
            raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: fingerprint {path}: {exc}") from exc
        if (verified.st_size, verified.st_mtime_ns, verified.st_ctime_ns) != (
            details.st_size,
            details.st_mtime_ns,
            details.st_ctime_ns,
        ):
            raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: unstable file during fingerprint {path}")
        fingerprint_bytes += planned_bytes
        result[rel] = (details.st_size, details.st_mtime_ns, details.st_ctime_ns, fingerprint)

    if not recursive:
        entries = None
        try:
            entries = os.scandir(root)
            for entry in entries:
                entry_path = Path(entry.path)
                rel_entry = str(entry_path.relative_to(root)).replace("\\", "/")
                if _watch_path_excluded(rel_entry, excludes):
                    continue
                if entry.is_symlink() or is_symlink_or_reparse(entry_path):
                    record(entry_path, allow_link=True)
                    continue
                if entry.is_file(follow_symlinks=False):
                    record(entry_path)

            # B28: Inspect protected configuration files even if watch root is shallow
            for protected in sorted(DEFAULT_WATCH_REINCLUDES):
                for target in _case_insensitive_existing(root, protected):
                    target_rel = str(target.relative_to(root)).replace("\\", "/")
                    if target_rel in result:
                        continue
                    if target.is_file():
                        record(target)
                    elif target.is_dir():
                        try:
                            for curr, dirs, files in os.walk(target):
                                current_path = Path(curr)
                                surviving_dirs: list[str] = []
                                for d in dirs:
                                    candidate = current_path / d
                                    cand_rel = str(candidate.relative_to(root)).replace("\\", "/")
                                    if is_reinclude_noise_path(cand_rel):
                                        continue
                                    if is_symlink_or_reparse(candidate):
                                        raise WatchScanUnavailableError(
                                            f"WATCH_SCAN_UNAVAILABLE: reparse or junction directory {candidate}"
                                        )
                                    surviving_dirs.append(d)
                                dirs[:] = surviving_dirs
                                for f in files:
                                    sub_path = current_path / f
                                    sub_rel = str(sub_path.relative_to(root)).replace("\\", "/")
                                    if sub_rel not in result:
                                        record(sub_path)
                        except OSError:
                            pass
        except OSError as exc:
            raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: enumerate {root}: {exc}") from exc
        finally:
            close = getattr(entries, "close", None)
            if close is not None:
                close()
        return WatchScanResult(root_exists=True, files=result)

    walk_errors: list[OSError] = []
    for current, dirs, files in os.walk(root, onerror=walk_errors.append):
        current_path = Path(current)
        surviving_dirs: list[str] = []
        for name in dirs:
            candidate = current_path / name
            rel_dir = str(candidate.relative_to(root)).replace("\\", "/")
            if is_reinclude_noise_path(rel_dir):
                continue
            if _watch_path_excluded(rel_dir, excludes) and not (
                is_protected_watch_dir_ancestor(rel_dir) or is_under_reinclude_tree(rel_dir)
            ):
                continue
            if is_symlink_or_reparse(candidate):
                raise WatchScanUnavailableError(
                    f"WATCH_SCAN_UNAVAILABLE: reparse or junction directory {candidate}"
                )
            surviving_dirs.append(name)
        dirs[:] = surviving_dirs
        for name in files:
            record(current_path / name)
    if walk_errors:
        raise WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: walk {root}: {walk_errors[0]}")
    return WatchScanResult(root_exists=True, files=result)


@dataclass(frozen=True)
class WatchRootsSnapshot:
    """Snapshot of watched directories to detect external file mutations."""

    roots: tuple[Path, ...]
    initial_state: dict[Path, WatchScanResult]
    started_ns: int
    excludes: frozenset[str]
    recursive_roots: frozenset[Path]
    max_files_per_root: int
    max_fingerprint_bytes_per_root: int

    def assert_unchanged(self, effect_recorder: list[dict[str, Any]] | None = None) -> None:
        for root in self.roots:
            try:
                current_scan = _scan_watch_root(
                    root,
                    excludes=self.excludes,
                    recursive=root in self.recursive_roots,
                    max_files=self.max_files_per_root,
                    max_fingerprint_bytes=self.max_fingerprint_bytes_per_root,
                )
            except (WatchScanUnavailableError, PathSecurityError) as exc:
                reason = getattr(exc, "error_class", "WATCH_SCAN_UNAVAILABLE")
                if reason not in {
                    "WATCH_SCAN_UNAVAILABLE",
                    "WATCH_ROOT_BUDGET_EXCEEDED",
                    "WATCH_FINGERPRINT_BUDGET_EXCEEDED",
                }:
                    raise
                if effect_recorder is not None:
                    effect_recorder.append(
                        {"effect": "WATCH_SCAN", "state": "UNKNOWN", "root": str(root), "reason": reason}
                    )
                raise
            old_scan = self.initial_state[root]
            old = old_scan.files
            current = current_scan.files
            candidates = sorted(path for path in old.keys() | current.keys() if old.get(path) != current.get(path))
            changes: list[dict[str, Any]] = []
            if old_scan.root_exists != current_scan.root_exists:
                changes.append(
                    {
                        "path": ".",
                        "before": {"root_exists": old_scan.root_exists},
                        "after": {"root_exists": current_scan.root_exists},
                        "sha256": None,
                    }
                )
            for rel in candidates:
                metadata = current.get(rel)
                evidence: dict[str, Any] = {
                    "path": rel,
                    "before": old.get(rel),
                    "after": metadata,
                    "sha256": metadata[3] if metadata is not None else None,
                }
                changes.append(evidence)
            if changes:
                changed_paths = [str(c["path"]) for c in changes]
                if effect_recorder is not None:
                    effect_recorder.append(
                        {
                            "effect": "EXTERNAL_WRITE",
                            "state": "UNKNOWN",
                            "root": str(root),
                            "changes": changes,
                        }
                    )
                raise ExternalWriteDetectedError(
                    f"External write detected in watch root '{root}'",
                    effect_state="UNKNOWN",
                    changed_paths=changed_paths,
                )


def snapshot_watch_roots(
    roots: Sequence[Path],
    *,
    excludes: Sequence[str] | None = None,
    recursive_roots: Sequence[Path] | None = None,
    max_files_per_root: int = 50_000,
    max_fingerprint_bytes_per_root: int = 64 * 1024 * 1024,
    effect_recorder: list[dict[str, Any]] | None = None,
) -> WatchRootsSnapshot:
    """Take a bounded full-content fingerprint snapshot; roots are shallow unless recursive."""
    if max_files_per_root <= 0:
        raise ValueError("max_files_per_root must be positive")
    if max_fingerprint_bytes_per_root <= 0:
        raise ValueError("max_fingerprint_bytes_per_root must be positive")
    custom_excludes = frozenset(name.replace("\\", "/").casefold() for name in (excludes or ()))
    default_excludes = frozenset(name.replace("\\", "/").casefold() for name in DEFAULT_WATCH_EXCLUDES)
    exclude_names = default_excludes | custom_excludes
    recursive = frozenset(path.resolve() for path in (recursive_roots or ()))
    state: dict[Path, WatchScanResult] = {}
    resolved_roots: list[Path] = []
    for r in roots:
        if is_symlink_or_reparse(r):
            exc = WatchScanUnavailableError(f"WATCH_SCAN_UNAVAILABLE: watch root is reparse or symlink {r}")
            if effect_recorder is not None:
                effect_recorder.append(
                    {"effect": "WATCH_SCAN", "state": "UNKNOWN", "root": str(r), "reason": exc.error_class}
                )
            raise exc
        cr = r.resolve()
        resolved_roots.append(cr)
        try:
            state[cr] = _scan_watch_root(
                cr,
                excludes=exclude_names,
                recursive=cr in recursive,
                max_files=max_files_per_root,
                max_fingerprint_bytes=max_fingerprint_bytes_per_root,
            )
        except (WatchScanUnavailableError, PathSecurityError) as exc:
            reason = getattr(exc, "error_class", "WATCH_SCAN_UNAVAILABLE")
            if reason not in {
                "WATCH_SCAN_UNAVAILABLE",
                "WATCH_ROOT_BUDGET_EXCEEDED",
                "WATCH_FINGERPRINT_BUDGET_EXCEEDED",
            }:
                raise
            if effect_recorder is not None:
                effect_recorder.append(
                    {"effect": "WATCH_SCAN", "state": "UNKNOWN", "root": str(cr), "reason": reason}
                )
            raise
    return WatchRootsSnapshot(
        roots=tuple(resolved_roots),
        initial_state=state,
        started_ns=time.time_ns(),
        excludes=exclude_names,
        recursive_roots=recursive,
        max_files_per_root=max_files_per_root,
        max_fingerprint_bytes_per_root=max_fingerprint_bytes_per_root,
    )
