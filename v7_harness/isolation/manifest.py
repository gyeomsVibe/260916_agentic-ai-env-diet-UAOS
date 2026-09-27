"""Deterministic manifest generation and content-addressed patch bundle."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from v7_harness.isolation.errors import (
    PatchHashMismatchError,
    ReparsePointError,
)
from v7_harness.isolation.security import (
    assert_no_reparse_or_symlink,
    check_case_alias_set,
    is_symlink_or_reparse,
    validate_safe_relative_path,
)

DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    ".coord/receipts",
    ".work",
    ".coord/pilot",
    # U15: 세 도구가 파일럿 실행 중에도 조율 사건을 기록해야 하므로 스트림과 브리핑은
    # 원본 매니페스트에서 제외한다. 제외하지 않으면 기록 한 줄이 SOURCE_DIVERGED를 만든다.
    ".coord/stream",
    ".coord/mailbox",  # Runtime mailbox is transport evidence and must not trigger SOURCE_DIVERGED
    ".coord/usage",    # Runtime telemetry ledger and must not trigger SOURCE_DIVERGED
    ".coord/presence",  # Heartbeats written by other tools' session hooks while a pilot runs
    ".coord/codex_brief.md",
    # U48-W1: `pilot run` defaults to `--work-dir .coord`, which puts the broker DB and its writer lock inside the
    # source. The pilot holds that lock with a byte lock while it hashes the source, so reading it raised
    # PermissionError. The staging copy also lives there and is written during the run. None of it is source.
    # `.coord/runs` stays in: 177 tracked records live there, including the regression entry point; the pilot excludes
    # only its own task's run folder (pilot.work_dir_excludes), which also covers a --work-dir elsewhere in the source.
    ".coord/coord.sqlite3",
    ".coord/coord.sqlite3-wal",
    ".coord/coord.sqlite3-shm",
    ".coord/coord.sqlite3-journal",
    ".coord/coord.sqlite3.writer.lock",
    ".coord/stage",
}

# A broker writer lock anywhere in the source (a --work-dir nested elsewhere) is held with a byte lock while the pilot
# hashes the source, and holds no content.
_WRITER_LOCK_SUFFIX = ".sqlite3.writer.lock"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int
    sha256: str
    is_executable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeterministicManifest:
    entries: list[ManifestEntry]
    manifest_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "manifest_hash": self.manifest_hash,
        }

    def to_canonical_json(self) -> bytes:
        raw = [e.to_dict() for e in self.entries]
        return json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeterministicManifest:
        entries = [ManifestEntry(**item) for item in data.get("entries", [])]
        return cls(entries=entries, manifest_hash=data["manifest_hash"])

    def get_entry(self, path: str) -> ManifestEntry | None:
        norm = path.replace("\\", "/").strip()
        for e in self.entries:
            if e.path == norm:
                return e
        return None


def build_manifest(root_dir: Path, excludes: Sequence[str] | None = None) -> DeterministicManifest:
    """Walk root directory deterministically, rejecting symlinks/reparse points."""
    canonical_root = root_dir.resolve()
    assert_no_reparse_or_symlink(canonical_root)

    exclude_set = set(DEFAULT_EXCLUDES)
    if excludes:
        exclude_set.update(excludes)

    entries: list[ManifestEntry] = []
    discovered_paths: list[str] = []

    for root, dirs, files in os.walk(canonical_root):
        root_path = Path(root)

        # Check directory itself
        if is_symlink_or_reparse(root_path):
            raise ReparsePointError(f"Directory is symlink/reparse point: {root_path}")

        # Filter excluded dirs and check reparse points
        surviving_dirs: list[str] = []
        for d in dirs:
            dir_full = root_path / d
            if is_symlink_or_reparse(dir_full):
                raise ReparsePointError(f"Subdirectory is symlink/reparse point: {dir_full}")
            rel_d = str(dir_full.relative_to(canonical_root)).replace("\\", "/")
            if d in exclude_set or rel_d in exclude_set:
                continue
            surviving_dirs.append(d)
        dirs[:] = surviving_dirs

        for f in files:
            if f.endswith(".pyc") or f.endswith(_WRITER_LOCK_SUFFIX):
                continue
            file_full = root_path / f
            if is_symlink_or_reparse(file_full):
                raise ReparsePointError(f"File is symlink/reparse point: {file_full}")

            rel_str = str(file_full.relative_to(canonical_root)).replace("\\", "/")
            if any(rel_str == ex or rel_str.startswith(ex + "/") for ex in exclude_set):
                continue
            if rel_str.startswith(".claude/codex-relay/") and rel_str.endswith(".log"):
                continue

            st = file_full.stat()
            # Sockets, FIFOs and devices hold no source content; opening a socket raised ENXIO and a FIFO would block.
            if not stat.S_ISREG(st.st_mode):
                continue

            safe_rel = validate_safe_relative_path(rel_str)
            discovered_paths.append(safe_rel)

            size = st.st_size
            sha256 = _sha256_file(file_full)
            is_exec = bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

            entries.append(
                ManifestEntry(
                    path=safe_rel,
                    size=size,
                    sha256=sha256,
                    is_executable=is_exec,
                )
            )

    # Fail closed on case alias collisions
    check_case_alias_set(discovered_paths)

    # Sort deterministically by path
    entries.sort(key=lambda e: e.path)

    # Compute manifest hash from canonical JSON
    raw = [e.to_dict() for e in entries]
    manifest_bytes = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_hash = _sha256_bytes(manifest_bytes)

    return DeterministicManifest(entries=entries, manifest_hash=manifest_hash)


@dataclass(frozen=True)
class PatchItem:
    path: str
    change_type: str  # "ADDED", "MODIFIED", "DELETED", "RENAMED"
    base_sha256: str | None
    target_sha256: str | None
    patch_data: str
    patch_hash: str
    rename_from: str | None = None
    content_kind: str = "text"  # "text" | "binary"
    delta_kind: str = "content"  # "content" | "newline" | "encoding"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PatchBundle:
    bundle_id: str
    base_manifest_hash: str
    target_manifest_hash: str
    items: list[PatchItem]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "base_manifest_hash": self.base_manifest_hash,
            "target_manifest_hash": self.target_manifest_hash,
            "items": [item.to_dict() for item in self.items],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatchBundle:
        items = [PatchItem(**i) for i in data.get("items", [])]
        return cls(
            bundle_id=data["bundle_id"],
            base_manifest_hash=data["base_manifest_hash"],
            target_manifest_hash=data["target_manifest_hash"],
            items=items,
            metadata=data.get("metadata", {}),
        )

    def verify_integrity(self) -> None:
        """Verify content hashes, bundle identity, and case alias safety."""
        # 1. Item-level patch hash check
        paths: list[str] = []
        for item in self.items:
            expected_patch_hash = _sha256_bytes(item.patch_data.encode("utf-8"))
            if item.patch_hash != expected_patch_hash:
                raise PatchHashMismatchError(
                    f"Patch hash mismatch for '{item.path}': recorded={item.patch_hash} computed={expected_patch_hash}"
                )
            paths.append(item.path)
            if item.rename_from is not None:
                paths.append(item.rename_from)

        # 2. Case alias check
        check_case_alias_set(paths)

        # 3. Content-addressed bundle_id verification
        expected_bundle_id = compute_bundle_id(
            base_manifest_hash=self.base_manifest_hash,
            target_manifest_hash=self.target_manifest_hash,
            items=self.items,
            metadata=self.metadata,
        )
        if self.bundle_id != expected_bundle_id:
            raise PatchHashMismatchError(
                f"Bundle ID mismatch: recorded={self.bundle_id} computed={expected_bundle_id}"
            )


def compute_bundle_id(
    base_manifest_hash: str,
    target_manifest_hash: str,
    items: Sequence[PatchItem],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Compute deterministic SHA-256 bundle ID."""
    canonical_items = [item.to_dict() for item in sorted(items, key=lambda i: i.path)]
    payload = {
        "base_manifest_hash": base_manifest_hash,
        "target_manifest_hash": target_manifest_hash,
        "items": canonical_items,
        "metadata": metadata or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data


def _detect_delta_kind(b1: bytes, b2: bytes) -> str:
    # Check newline-only difference
    if b1.replace(b"\r\n", b"\n") == b2.replace(b"\r\n", b"\n"):
        return "newline"
    # Check encoding-only difference
    for enc1 in ("utf-8", "latin-1", "cp1252"):
        for enc2 in ("utf-8", "latin-1", "cp1252"):
            if enc1 != enc2:
                try:
                    if b1.decode(enc1) == b2.decode(enc2):
                        return "encoding"
                except Exception:
                    pass
    return "content"


def create_patch_bundle(
    base_manifest: DeterministicManifest,
    target_manifest: DeterministicManifest,
    base_dir: Path,
    target_dir: Path,
    metadata: dict[str, Any] | None = None,
) -> PatchBundle:
    """Generate deterministic content-addressed patch bundle comparing base and target."""
    base_map = {e.path: e for e in base_manifest.entries}
    target_map = {e.path: e for e in target_manifest.entries}

    deleted_paths = sorted([p for p in base_map if p not in target_map])
    added_paths = sorted([p for p in target_map if p not in base_map])
    common_paths = sorted([p for p in base_map if p in target_map])

    # 1. Match RENAMED items (identical sha256)
    matched_renames: dict[str, str] = {}  # added_path -> deleted_path
    for a in list(added_paths):
        a_entry = target_map[a]
        for d in list(deleted_paths):
            d_entry = base_map[d]
            if a_entry.sha256 == d_entry.sha256:
                matched_renames[a] = d
                added_paths.remove(a)
                deleted_paths.remove(d)
                break

    items: list[PatchItem] = []

    # 2. Process Renamed
    for a, d in matched_renames.items():
        patch_data = f"RENAMED:{d}->{a}\n"
        patch_hash = _sha256_bytes(patch_data.encode("utf-8"))
        target_file = target_dir / a
        content_kind = "text"
        try:
            if target_file.exists() and _is_binary(target_file.read_bytes()):
                content_kind = "binary"
        except Exception:
            pass
        items.append(
            PatchItem(
                path=a,
                change_type="RENAMED",
                base_sha256=base_map[d].sha256,
                target_sha256=target_map[a].sha256,
                patch_data=patch_data,
                patch_hash=patch_hash,
                rename_from=d,
                content_kind=content_kind,
                delta_kind="content",
            )
        )

    # 3. Process Deleted
    for d in deleted_paths:
        base_entry = base_map[d]
        patch_data = f"--- a/{d}\n+++ /dev/null\n@@ -1,0 +0,0 @@\n-DELETED\n"
        patch_hash = _sha256_bytes(patch_data.encode("utf-8"))
        items.append(
            PatchItem(
                path=d,
                change_type="DELETED",
                base_sha256=base_entry.sha256,
                target_sha256=None,
                patch_data=patch_data,
                patch_hash=patch_hash,
                content_kind="text",
                delta_kind="content",
            )
        )

    # 4. Process Added
    for a in added_paths:
        target_entry = target_map[a]
        target_file = target_dir / a
        raw_bytes = b""
        try:
            raw_bytes = target_file.read_bytes()
        except Exception:
            pass
        content_kind = "binary" if _is_binary(raw_bytes) else "text"
        if content_kind == "binary":
            patch_data = f"BINARY_ADDED:{target_entry.sha256}\n"
        else:
            content = raw_bytes.decode("utf-8", errors="replace")
            diff_lines = difflib.unified_diff(
                [],
                content.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{a}",
            )
            patch_data = "".join(diff_lines)
            if not patch_data:
                patch_data = f"--- /dev/null\n+++ b/{a}\n@@ -0,0 +1 @@\n+{content}\n"
        patch_hash = _sha256_bytes(patch_data.encode("utf-8"))
        items.append(
            PatchItem(
                path=a,
                change_type="ADDED",
                base_sha256=None,
                target_sha256=target_entry.sha256,
                patch_data=patch_data,
                patch_hash=patch_hash,
                content_kind=content_kind,
                delta_kind="content",
            )
        )

    # 5. Process Modified (Common paths with differing sha256)
    for p in common_paths:
        base_entry = base_map[p]
        target_entry = target_map[p]
        if base_entry.sha256 != target_entry.sha256:
            base_file = base_dir / p
            target_file = target_dir / p
            base_bytes = b""
            target_bytes = b""
            try:
                base_bytes = base_file.read_bytes()
                target_bytes = target_file.read_bytes()
            except Exception:
                pass

            is_bin = _is_binary(base_bytes) or _is_binary(target_bytes)
            content_kind = "binary" if is_bin else "text"
            delta_kind = _detect_delta_kind(base_bytes, target_bytes)

            if content_kind == "binary" or len(target_bytes) > 512 * 1024:
                patch_data = f"BINARY_DIFF:{base_entry.sha256}->{target_entry.sha256}\n"
            else:
                try:
                    base_content = base_bytes.decode("utf-8", errors="replace")
                    target_content = target_bytes.decode("utf-8", errors="replace")
                    diff_lines = difflib.unified_diff(
                        base_content.splitlines(keepends=True),
                        target_content.splitlines(keepends=True),
                        fromfile=f"a/{p}",
                        tofile=f"b/{p}",
                    )
                    patch_data = "".join(diff_lines)
                except Exception:
                    patch_data = f"DIFF:{base_entry.sha256}->{target_entry.sha256}\n"
                if not patch_data:
                    patch_data = f"MODIFIED:{base_entry.sha256}->{target_entry.sha256}\n"

            patch_hash = _sha256_bytes(patch_data.encode("utf-8"))
            items.append(
                PatchItem(
                    path=p,
                    change_type="MODIFIED",
                    base_sha256=base_entry.sha256,
                    target_sha256=target_entry.sha256,
                    patch_data=patch_data,
                    patch_hash=patch_hash,
                    content_kind=content_kind,
                    delta_kind=delta_kind,
                )
            )

    # Sort items deterministically
    items.sort(key=lambda i: i.path)

    # Ensure no prompts or raw payload in metadata
    clean_meta = dict(metadata or {})
    for forbidden in ("prompt", "payload", "raw_task_payload"):
        clean_meta.pop(forbidden, None)

    bundle_id = compute_bundle_id(
        base_manifest_hash=base_manifest.manifest_hash,
        target_manifest_hash=target_manifest.manifest_hash,
        items=items,
        metadata=clean_meta,
    )

    bundle = PatchBundle(
        bundle_id=bundle_id,
        base_manifest_hash=base_manifest.manifest_hash,
        target_manifest_hash=target_manifest.manifest_hash,
        items=items,
        metadata=clean_meta,
    )
    bundle.verify_integrity()
    return bundle
