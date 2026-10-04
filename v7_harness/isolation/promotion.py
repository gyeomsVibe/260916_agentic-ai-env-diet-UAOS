"""Promotion dry-run engine with fail-closed safety and zero source mutation."""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from v7_harness.contracts.database import validate_promotion_candidate
from v7_harness.execution.errors import StaleFenceError
from v7_harness.isolation.errors import (
    ConcurrentOwnershipError,
    LiveMutationProhibitedError,
    PatchHashMismatchError,
    ScopeExpansionError,
    SourceDivergenceError,
    SourceMutationError,
    StaleFenceOrReceiptError,
    UntrackedOverwriteError,
    UnresolvedEffectError,
)
from v7_harness.isolation.manifest import (
    PatchBundle,
    build_manifest,
)
from v7_harness.isolation.security import (
    assert_no_reparse_or_symlink,
    check_case_match_on_disk,
    check_scope_confinement,
    validate_canonical_path_in_root,
    validate_safe_relative_path,
)


@dataclass(frozen=True)
class PromotionDryRunResult:
    success: bool
    status: str  # "DRY_RUN_PASSED", "APPROVAL_REQUIRED", "REJECTED"
    changes: list[dict[str, Any]]
    hashes: dict[str, str]
    conflicts: list[str]
    approval_required_actions: list[dict[str, Any]]
    source_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def dry_run_promotion(
    *,
    source_dir: Path,
    patch_bundle: PatchBundle,
    connection: sqlite3.Connection | None = None,
    attempt_id: str | None = None,
    resource_id: str | None = None,
    fencing_token: int | None = None,
    current_fence: int | None = None,
    reconciliation_log: list[dict[str, Any]] | None = None,
    acceptance_hash: str | None = None,
    allowed_scopes: Sequence[str | Path] | None = None,
    current_owner: str | None = None,
    active_leases: Sequence[dict[str, Any]] | None = None,
    excludes: Sequence[str] | None = None,
) -> PromotionDryRunResult:
    """
    Perform fail-closed promotion dry-run with ZERO mutation to source_dir.

    Fails closed on:
    - canonical path outside lease root / '..' escape / UNC / ADS
    - symlink, junction, or reparse point
    - case alias collision or on-disk casing mismatch
    - base manifest divergence (TOCTOU)
    - stale fence or missing PASS receipt
    - UNKNOWN / INTENDED / FAILED effects
    - patch hash mismatch
    - scope expansion outside allowed_scopes
    - untracked overwrite
    - same-file concurrent ownership
    """
    canonical_source = source_dir.resolve()
    assert_no_reparse_or_symlink(canonical_source)

    # 1. Take initial source snapshot to verify zero mutation at end
    initial_manifest = build_manifest(canonical_source, excludes=excludes)
    initial_hash = initial_manifest.manifest_hash

    # Stale fence verification (explicit fence args)
    if fencing_token is not None and current_fence is not None:
        if fencing_token < current_fence:
            if reconciliation_log is not None:
                reconciliation_log.append(
                    {
                        "reason": "STALE_FENCE",
                        "attempt_id": attempt_id,
                        "fencing_token": fencing_token,
                        "current_fence": current_fence,
                    }
                )
            raise StaleFenceOrReceiptError(
                f"Stale fence token: token={fencing_token} current={current_fence}"
            )

    # 2. Database validation (if connection is provided)
    if connection is not None:
        if attempt_id is not None and resource_id is not None and fencing_token is not None and acceptance_hash is not None:
            try:
                validate_promotion_candidate(
                    connection,
                    attempt_id=attempt_id,
                    resource_id=resource_id,
                    fencing_token=fencing_token,
                    acceptance_hash=acceptance_hash,
                )
            except StaleFenceError as exc:
                raise StaleFenceOrReceiptError(f"Stale fence token: {exc}") from exc
            except ValueError as exc:
                msg = str(exc)
                if "PASS_RECEIPT_REQUIRED" in msg:
                    raise StaleFenceOrReceiptError(f"PASS receipt required: {msg}") from exc
                elif "EFFECT_RECONCILIATION_REQUIRED" in msg:
                    raise UnresolvedEffectError(f"Effect reconciliation required: {msg}") from exc
                raise StaleFenceOrReceiptError(f"Promotion candidate rejected: {msg}") from exc

        # Check DB for concurrent active lease on the same resource
        if resource_id is not None:
            active_rows = connection.execute(
                "SELECT lease_id, owner, attempt_id FROM leases WHERE resource_id=? AND state='ACTIVE'",
                (resource_id,),
            ).fetchall()
            for lid, owner, att in active_rows:
                if (attempt_id and att != attempt_id) or (current_owner and owner != current_owner):
                    raise ConcurrentOwnershipError(
                        f"Concurrent ownership conflict on resource '{resource_id}': held by {owner} (lease {lid})"
                    )

    # 3. Check in-memory active lease conflicts
    if active_leases:
        bundle_paths = {item.path for item in patch_bundle.items}
        for lease in active_leases:
            if lease.get("state") == "ACTIVE":
                l_res = lease.get("resource_id")
                l_owner = lease.get("owner")
                l_att = lease.get("attempt_id")
                l_paths = set(lease.get("paths", []))
                has_res_conflict = resource_id and l_res == resource_id
                has_path_conflict = bool(bundle_paths & l_paths)

                if has_res_conflict or has_path_conflict:
                    if (attempt_id and l_att != attempt_id) or (current_owner and l_owner != current_owner):
                        raise ConcurrentOwnershipError(
                            f"Concurrent ownership conflict: active lease {lease.get('lease_id')} held by {l_owner}"
                        )

    # 4. Patch bundle integrity
    patch_bundle.verify_integrity()

    # 5. Source divergence / TOCTOU check
    if initial_hash != patch_bundle.base_manifest_hash:
        raise SourceDivergenceError(
            f"Source diverged from base manifest: base={patch_bundle.base_manifest_hash} "
            f"current_source={initial_hash}"
        )

    # Fast-path for empty bundle (no changes)
    if not patch_bundle.items:
        return PromotionDryRunResult(
            success=True,
            status="DRY_RUN_PASSED",
            changes=[],
            hashes={
                "base_manifest_hash": patch_bundle.base_manifest_hash,
                "target_manifest_hash": patch_bundle.target_manifest_hash,
                "bundle_id": patch_bundle.bundle_id,
                "current_source_hash": initial_hash,
            },
            conflicts=[],
            approval_required_actions=[],
            source_mutated=False,
        )

    # 5b. Shared consensus spec modification check
    bundle_meta = patch_bundle.metadata or {}
    spec_reqs = bundle_meta.get("spec_change_requests", None)
    for item in patch_bundle.items:
        if "CONSENSUS" in item.path.upper() or "SPEC" in item.path.upper():
            if spec_reqs is not None and len(spec_reqs) == 0:
                raise ScopeExpansionError(
                    f"Shared spec modification '{item.path}' rejected without approved spec_change_requests"
                )

    # 6. Evaluate all changes without mutating source
    changes: list[dict[str, Any]] = []
    approval_required_actions: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for item in patch_bundle.items:
        if item.rename_from is not None:
            rename_from = validate_safe_relative_path(item.rename_from)
            check_scope_confinement(rename_from, allowed_scopes)
        safe_rel = validate_safe_relative_path(item.path)
        target_path = validate_canonical_path_in_root(canonical_source, safe_rel)

        # Check symlink/reparse
        assert_no_reparse_or_symlink(target_path, root=canonical_source)

        # Check scope expansion
        check_scope_confinement(safe_rel, allowed_scopes)

        # Check on-disk case alias
        check_case_match_on_disk(canonical_source, safe_rel)

        if item.change_type == "ADDED":
            if target_path.exists():
                raise UntrackedOverwriteError(
                    f"Untracked file overwrite forbidden: '{safe_rel}' already exists on disk"
                )
            approval_required_actions.append(
                {"action": "ADD_FILE", "path": safe_rel, "approval_required": True}
            )
        elif item.change_type == "MODIFIED":
            if not target_path.exists():
                raise SourceDivergenceError(
                    f"Modified target file does not exist on disk: '{safe_rel}'"
                )
            approval_required_actions.append(
                {"action": "OVERWRITE_FILE", "path": safe_rel, "approval_required": True}
            )
        elif item.change_type == "DELETED":
            # Deletion is always flagged as an action requiring explicit user approval
            approval_required_actions.append(
                {"action": "DELETE_FILE", "path": safe_rel, "approval_required": True}
            )
        elif item.change_type == "RENAMED":
            if item.rename_from is None:
                raise PatchHashMismatchError(f"Rename source missing for '{safe_rel}'")
            approval_required_actions.extend(
                [
                    {"action": "DELETE_FILE", "path": item.rename_from, "approval_required": True},
                    {"action": "ADD_FILE", "path": safe_rel, "approval_required": True},
                ]
            )

        changes.append(
            {
                "path": safe_rel,
                "change_type": item.change_type,
                "base_sha256": item.base_sha256,
                "target_sha256": item.target_sha256,
                "patch_hash": item.patch_hash,
                "rename_from": item.rename_from,
            }
        )

    # 7. Post-check ZERO source mutation
    post_manifest = build_manifest(canonical_source, excludes=excludes)
    if post_manifest.manifest_hash != initial_hash:
        raise SourceMutationError("CRITICAL INVARIANT VIOLATION: Source was mutated during dry-run promotion!")

    return PromotionDryRunResult(
        success=True,
        status="DRY_RUN_PASSED" if not approval_required_actions else "APPROVAL_REQUIRED",
        changes=changes,
        hashes={
            "base_manifest_hash": patch_bundle.base_manifest_hash,
            "target_manifest_hash": patch_bundle.target_manifest_hash,
            "bundle_id": patch_bundle.bundle_id,
            "current_source_hash": initial_hash,
        },
        conflicts=conflicts,
        approval_required_actions=approval_required_actions,
        source_mutated=False,
    )


def apply_promotion(
    *,
    source_dir: Path,
    staging_dir: Path,
    patch_bundle: PatchBundle,
    approve_bundle_id: str,
    excludes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Apply approved promotion patch bundle from staging to source with fail-closed safety."""
    from v7_harness.isolation.errors import IsolationError
    from v7_harness.isolation.manifest import _sha256_file

    # 1. Approval bundle ID match
    if approve_bundle_id != patch_bundle.bundle_id:
        raise IsolationError(
            f"Approval mismatch: expected {patch_bundle.bundle_id}, got {approve_bundle_id}"
        )

    # 2. Rejection of DELETED or RENAMED items
    for item in patch_bundle.items:
        if item.change_type in ("DELETED", "RENAMED"):
            raise IsolationError(f"Live mutation does not support {item.change_type}: {item.path}")

    canonical_source = source_dir.resolve()
    canonical_staging = staging_dir.resolve()
    assert_no_reparse_or_symlink(canonical_source)
    assert_no_reparse_or_symlink(canonical_staging)

    # 3. Patch bundle integrity and source divergence (TOCTOU)
    patch_bundle.verify_integrity()

    current_source_manifest = build_manifest(canonical_source, excludes=excludes)
    if current_source_manifest.manifest_hash != patch_bundle.base_manifest_hash:
        raise SourceDivergenceError(
            f"Source diverged from base manifest: base={patch_bundle.base_manifest_hash} "
            f"current_source={current_source_manifest.manifest_hash}"
        )

    # 4. Preflight all items: paths, symlinks, untracked overwrites, and staging content hashes
    staging_copies: list[tuple[Path, Path, str]] = []
    for item in patch_bundle.items:
        if item.change_type not in ("ADDED", "MODIFIED"):
            raise IsolationError(f"Unsupported change type: {item.change_type}")

        safe_rel = validate_safe_relative_path(item.path)
        src_path = validate_canonical_path_in_root(canonical_source, safe_rel)
        stg_path = validate_canonical_path_in_root(canonical_staging, safe_rel)

        assert_no_reparse_or_symlink(src_path, root=canonical_source)
        assert_no_reparse_or_symlink(stg_path, root=canonical_staging)

        if not stg_path.is_file():
            raise IsolationError(f"Staging file missing: {safe_rel}")

        actual_stg_sha = _sha256_file(stg_path)
        if actual_stg_sha != item.target_sha256:
            raise IsolationError(
                f"Staging file content modified after bundle: '{safe_rel}' "
                f"expected={item.target_sha256} actual={actual_stg_sha}"
            )

        if item.change_type == "ADDED":
            if src_path.exists():
                raise UntrackedOverwriteError(f"Untracked overwrite forbidden for ADDED file: {safe_rel}")
        elif item.change_type == "MODIFIED":
            if not src_path.exists():
                raise SourceDivergenceError(f"Modified target file does not exist on disk: {safe_rel}")
            check_case_match_on_disk(canonical_source, safe_rel)

        staging_copies.append((stg_path, src_path, safe_rel))

    # 5. Prepare every payload and backup on the source volume before mutating source.
    # U145: not tempfile.mkdtemp. On Python 3.13+ Windows its 0o700 DACL is private and protected, and os.replace
    # carried it into source, so sandboxed readers lost access. A default-mode mkdir inherits the parent's ACEs;
    # uuid4 keeps the name unique and the same parent keeps os.replace on one volume.
    transaction_root = canonical_source.parent / f".{canonical_source.name}.promotion-{uuid.uuid4().hex}"
    transaction_root.mkdir()
    payload_root = transaction_root / "payload"
    backup_root = transaction_root / "backup"
    prepared: list[tuple[Path, Path, Path | None, str]] = []
    applied: list[str] = []
    created_dirs: list[Path] = []
    try:
        for stg_path, src_path, safe_rel in staging_copies:
            payload_path = payload_root / safe_rel
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stg_path, payload_path)
            backup_path: Path | None = None
            if src_path.exists():
                backup_path = backup_root / safe_rel
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, backup_path)
            prepared.append((payload_path, src_path, backup_path, safe_rel))

        # Each file replacement is atomic. If any replacement fails, restore every
        # earlier target so callers never observe a completed partial promotion.
        try:
            for payload_path, src_path, _backup_path, safe_rel in prepared:
                missing: list[Path] = []
                parent = src_path.parent
                while parent != canonical_source and not parent.exists():
                    missing.append(parent)
                    parent = parent.parent
                src_path.parent.mkdir(parents=True, exist_ok=True)
                created_dirs.extend(reversed(missing))
                os.replace(payload_path, src_path)
                applied.append(safe_rel)
        except Exception:
            for _payload_path, src_path, backup_path, safe_rel in reversed(prepared):
                if safe_rel not in applied:
                    continue
                if backup_path is None:
                    src_path.unlink(missing_ok=True)
                else:
                    os.replace(backup_path, src_path)
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
    finally:
        shutil.rmtree(transaction_root, ignore_errors=True)

    return {
        "applied": applied,
        "bundle_id": patch_bundle.bundle_id,
    }
